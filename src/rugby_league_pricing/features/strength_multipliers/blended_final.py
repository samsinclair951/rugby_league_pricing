"""Blend lineup/player strength into baseline strength multipliers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge


DEFAULT_RIDGE_ALPHA = 35.0
MIN_EXPECTED_POINTS = 0.5


# Raw features from team_lineups/strength.py.
OWN_SIGNAL_COLS = [
    "player_strength_signal",
    "top5_strength_on_field",
    "props_8_10_strength",
    "middle_pack_8_10_11_12_13_strength",
    "halves_6_7_strength",
    "spine_1_6_7_9_strength",
    "hooker_9_strength",
    "stand_off_6_strength",
    "scrum_half_7_strength",
    "missing_core_overall_sum",
    "missing_core_top3_sum",
    "missing_props_8_10_sum",
    "missing_middle_pack_8_10_11_12_13_sum",
    "missing_halves_6_7_sum",
    "missing_spine_1_6_7_9_sum",
    "missing_hooker_9_sum",
    "missing_stand_off_6_sum",
    "missing_scrum_half_7_sum",
]

OPPONENT_SIGNAL_COLS = [
    "opponent_player_strength_signal",
    "opponent_top5_strength_on_field",
    "opponent_halves_6_7_strength",
    "opponent_spine_1_6_7_9_strength",
    "opponent_missing_core_overall_sum",
    "opponent_missing_core_top3_sum",
    "opponent_missing_halves_6_7_sum",
    "opponent_missing_spine_1_6_7_9_sum",
]

RAW_FEATURE_COLS = OWN_SIGNAL_COLS + OPPONENT_SIGNAL_COLS

MODEL_FEATURE_COLS = [
    f"{column}_z"
    for column in RAW_FEATURE_COLS
] + [
    "high_disruption_flag",
    "is_home",
]


@dataclass
class PlayerBlendModel:
    """Fitted player-selection adjustment model."""

    model: Ridge
    feature_means: pd.Series
    feature_stds: pd.Series
    missing_top3_threshold: float
    missing_halves_threshold: float


def attach_opponent_features(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Attach the opponent's lineup-strength signals."""
    result = frame.copy()

    opponent = result[
        [
            "fixture_id",
            "team_id",
            "player_strength_signal",
            "top5_strength_on_field",
            "halves_6_7_strength",
            "spine_1_6_7_9_strength",
            "missing_core_overall_sum",
            "missing_core_top3_sum",
            "missing_halves_6_7_sum",
            "missing_spine_1_6_7_9_sum",
        ]
    ].rename(
        columns={
            "team_id": "opponent_id",
            "player_strength_signal": "opponent_player_strength_signal",
            "top5_strength_on_field": "opponent_top5_strength_on_field",
            "halves_6_7_strength": "opponent_halves_6_7_strength",
            "spine_1_6_7_9_strength": "opponent_spine_1_6_7_9_strength",
            "missing_core_overall_sum": "opponent_missing_core_overall_sum",
            "missing_core_top3_sum": "opponent_missing_core_top3_sum",
            "missing_halves_6_7_sum": "opponent_missing_halves_6_7_sum",
            "missing_spine_1_6_7_9_sum": "opponent_missing_spine_1_6_7_9_sum",
        }
    )

    return result.merge(
        opponent,
        on=["fixture_id", "opponent_id"],
        how="left",
        validate="one_to_one",
    )


def _prepare_features(
    frame: pd.DataFrame,
    *,
    means: pd.Series,
    stds: pd.Series,
    missing_top3_threshold: float,
    missing_halves_threshold: float,
) -> pd.DataFrame:
    """Create model-ready features using TRAINING-set scaling."""
    result = frame.copy()

    for column in RAW_FEATURE_COLS:
        if column not in result.columns:
            result[column] = 0.0

        result[column] = (
            pd.to_numeric(
                result[column],
                errors="coerce",
            )
            .fillna(0.0)
        )

        std = float(stds.get(column, 0.0))
        mean = float(means.get(column, 0.0))

        if std <= 0:
            result[f"{column}_z"] = 0.0
        else:
            result[f"{column}_z"] = (
                result[column] - mean
            ) / std

    result["high_disruption_flag"] = (
        (
            result["missing_core_top3_sum"]
            >= missing_top3_threshold
        )
        |
        (
            result["missing_halves_6_7_sum"]
            >= missing_halves_threshold
        )
    ).astype(int)

    result["is_home"] = (
        result["is_home"].astype(int)
    )

    return result


def fit_player_blend_model(
    historical_frame: pd.DataFrame,
    *,
    ridge_alpha: float = DEFAULT_RIDGE_ALPHA,
) -> PlayerBlendModel:
    """
    Fit the player-selection residual model.

    historical_frame must contain:
        points_for
        baseline_expected_points
        is_home
        raw lineup-strength features
        opponent lineup-strength features
    """
    train = historical_frame.copy()

    for column in RAW_FEATURE_COLS:
        if column not in train.columns:
            train[column] = 0.0

        train[column] = (
            pd.to_numeric(
                train[column],
                errors="coerce",
            )
            .fillna(0.0)
        )

    means = train[RAW_FEATURE_COLS].mean()
    stds = train[RAW_FEATURE_COLS].std(
        ddof=0
    )

    missing_top3_threshold = float(
        train[
            "missing_core_top3_sum"
        ].quantile(0.80)
    )

    missing_halves_threshold = float(
        train[
            "missing_halves_6_7_sum"
        ].quantile(0.80)
    )

    train = _prepare_features(
        train,
        means=means,
        stds=stds,
        missing_top3_threshold=(
            missing_top3_threshold
        ),
        missing_halves_threshold=(
            missing_halves_threshold
        ),
    )

    baseline = (
        train["baseline_expected_points"]
        .clip(lower=MIN_EXPECTED_POINTS)
    )

    target = np.log(
        (train["points_for"] + 0.5)
        / baseline
    )

    model = Ridge(
        alpha=ridge_alpha,
        fit_intercept=True,
    )

    model.fit(
        train[MODEL_FEATURE_COLS],
        target,
    )

    return PlayerBlendModel(
        model=model,
        feature_means=means,
        feature_stds=stds,
        missing_top3_threshold=(
            missing_top3_threshold
        ),
        missing_halves_threshold=(
            missing_halves_threshold
        ),
    )


def predict_selection_adjustments(
    lineup_strength: pd.DataFrame,
    blend_model: PlayerBlendModel,
) -> pd.DataFrame:
    """
    Predict the multiplicative expected-points adjustment
    for future lineups.
    """
    features = attach_opponent_features(
        lineup_strength
    )

    features = _prepare_features(
        features,
        means=blend_model.feature_means,
        stds=blend_model.feature_stds,
        missing_top3_threshold=(
            blend_model.missing_top3_threshold
        ),
        missing_halves_threshold=(
            blend_model.missing_halves_threshold
        ),
    )

    log_adjustment = blend_model.model.predict(
        features[MODEL_FEATURE_COLS]
    )

    result = features.copy()

    result["player_log_adjustment"] = (
        log_adjustment
    )

    result["score_adjustment_factor"] = (
        np.exp(log_adjustment)
    )

    return result


def build_final_strength_multipliers(
    baseline: pd.DataFrame,
    adjustments: pd.DataFrame,
    version_type: str,
) -> pd.DataFrame:
    """
    Apply player-selection adjustments to baseline multipliers.

    The current player model predicts expected-points residuals,
    so the adjustment is carried through the attack multiplier.

    Defence remains unchanged until a separate defensive
    residual model is validated.
    """
    adjustment_cols = [
        "fixture_id",
        "team_id",
        "score_adjustment_factor",
        "player_log_adjustment",
    ]

    result = baseline.merge(
        adjustments[adjustment_cols],
        on=[
            "fixture_id",
            "team_id",
        ],
        how="left",
        validate="one_to_one",
    )

    result[
        "score_adjustment_factor"
    ] = result[
        "score_adjustment_factor"
    ].fillna(1.0)

    result[
        "player_log_adjustment"
    ] = result[
        "player_log_adjustment"
    ].fillna(0.0)

    result["version_type"] = version_type

    result["scaled_attack_multiplier"] = (
        result["scaled_attack_multiplier"]
        * result["score_adjustment_factor"]
    )

    # Deliberately unchanged for now.
    result["scaled_defence_multiplier"] = (
        result["scaled_defence_multiplier"]
    )

    return result


def predict_from_stored_model(
    lineup_strength: pd.DataFrame,
    stored_model,
) -> pd.DataFrame:
    """Predict adjustments from a persisted model snapshot."""
    features = attach_opponent_features(
        lineup_strength
    )

    features = _prepare_features(
        features,
        means=stored_model.feature_means,
        stds=stored_model.feature_stds,
        missing_top3_threshold=(
            stored_model.missing_top3_threshold
        ),
        missing_halves_threshold=(
            stored_model.missing_halves_threshold
        ),
    )

    log_adjustment = pd.Series(
        stored_model.intercept,
        index=features.index,
        dtype=float,
    )

    for feature_name, coefficient in (
        stored_model.coefficients.items()
    ):
        if feature_name not in features.columns:
            raise ValueError(
                f"Missing model feature: {feature_name}"
            )

        log_adjustment += (
            features[feature_name]
            * float(coefficient)
        )

    result = features.copy()

    result["player_log_adjustment"] = (
        log_adjustment
    )

    result["score_adjustment_factor"] = (
        np.exp(log_adjustment)
    )

    result["model_version"] = (
        stored_model.model_version
    )

    return result