"""Core expected-score calculation helpers."""

from __future__ import annotations

import pandas as pd

from .constants import (
    EXPECTED_SCORE_COLUMNS,
    MODEL_FEATURE_COLUMNS,
    REQUIRED_SCORING_FACTOR_COLUMNS,
    REQUIRED_STRENGTH_COLUMNS,
)


def validate_columns(
    dataframe: pd.DataFrame,
    required_columns: set[str],
    dataframe_name: str,
) -> None:
    """Validate that a DataFrame contains the required columns."""
    missing_columns = required_columns.difference(dataframe.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"{dataframe_name} is missing required columns: {missing}")

    if dataframe["fixture_id"].duplicated().any():
        duplicate_fixture_ids = (
            dataframe.loc[
                dataframe["fixture_id"].duplicated(),
                "fixture_id",
            ]
            .astype(str)
            .tolist()
        )
        raise ValueError(
            f"{dataframe_name} contains duplicate fixture IDs: {duplicate_fixture_ids}"
        )


def _validate_input_frames(
    strength_multipliers: pd.DataFrame,
    scoring_factors: pd.DataFrame,
) -> None:
    """Validate both input DataFrames before calculating expected scores."""
    validate_columns(
        dataframe=strength_multipliers,
        required_columns=REQUIRED_STRENGTH_COLUMNS,
        dataframe_name="strength_multipliers",
    )

    validate_columns(
        dataframe=scoring_factors,
        required_columns=REQUIRED_SCORING_FACTOR_COLUMNS,
        dataframe_name="scoring_factors",
    )


def _merge_model_inputs(
    strength_multipliers: pd.DataFrame,
    scoring_factors: pd.DataFrame,
) -> pd.DataFrame:
    """Merge strength and scoring-factor data on fixture ID."""
    return strength_multipliers.merge(
        scoring_factors,
        on="fixture_id",
        how="left",
        validate="one_to_one",
    )


def _validate_model_features(
    expected_scores: pd.DataFrame,
    model_feature_columns: list[str] | None = None,
) -> None:
    """Ensure the model features are present and positive."""
    feature_columns = model_feature_columns or MODEL_FEATURE_COLUMNS

    missing_features = expected_scores[feature_columns].isna().any(axis=1)

    if missing_features.any():
        missing_fixture_ids = (
            expected_scores.loc[missing_features, "fixture_id"].astype(str).tolist()
        )
        raise ValueError(f"Missing model features for fixtures: {missing_fixture_ids}")

    non_positive_features = (expected_scores[feature_columns] <= 0).any(axis=1)

    if non_positive_features.any():
        invalid_fixture_ids = (
            expected_scores.loc[
                non_positive_features,
                "fixture_id",
            ]
            .astype(str)
            .tolist()
        )
        raise ValueError(
            "Model features must be greater than zero for fixtures: "
            f"{invalid_fixture_ids}"
        )


def _calculate_expected_values(expected_scores: pd.DataFrame) -> pd.DataFrame:
    """Calculate expected home/away points and derived score metrics."""
    expected_scores = expected_scores.copy()

    expected_scores["expected_home_points"] = (
        expected_scores["league_average_points"]
        * expected_scores["home_attack_multiplier"]
        * expected_scores["away_defence_multiplier"]
        * expected_scores["home_scoring_factor"]
    )

    expected_scores["expected_away_points"] = (
        expected_scores["league_average_points"]
        * expected_scores["away_attack_multiplier"]
        * expected_scores["home_defence_multiplier"]
        * expected_scores["away_scoring_factor"]
    )

    expected_scores["expected_margin"] = (
        expected_scores["expected_home_points"]
        - expected_scores["expected_away_points"]
    )

    expected_scores["expected_total_points"] = (
        expected_scores["expected_home_points"]
        + expected_scores["expected_away_points"]
    )

    return expected_scores


def calculate_expected_scores(
    strength_multipliers: pd.DataFrame,
    scoring_factors: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate expected home and away points for each fixture."""
    _validate_input_frames(
        strength_multipliers=strength_multipliers,
        scoring_factors=scoring_factors,
    )

    expected_scores = _merge_model_inputs(
        strength_multipliers=strength_multipliers,
        scoring_factors=scoring_factors,
    )

    _validate_model_features(expected_scores)
    expected_scores = _calculate_expected_values(expected_scores)

    return expected_scores[EXPECTED_SCORE_COLUMNS]
