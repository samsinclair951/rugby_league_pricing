"""Generate expected team scores from pre-match model features."""

from __future__ import annotations

import pandas as pd

REQUIRED_STRENGTH_COLUMNS = {
    "fixture_id",
    "home_attack_multiplier",
    "home_defence_multiplier",
    "away_attack_multiplier",
    "away_defence_multiplier",
}

REQUIRED_SCORING_FACTOR_COLUMNS = {
    "fixture_id",
    "league_average_points",
    "home_scoring_factor",
    "away_scoring_factor",
}

EXPECTED_SCORE_COLUMNS = [
    "fixture_id",
    "expected_home_points",
    "expected_away_points",
    "expected_margin",
    "expected_total_points",
]


def validate_columns(
    dataframe: pd.DataFrame,
    required_columns: set[str],
    dataframe_name: str,
) -> None:
    """Validate that a DataFrame contains the required columns.

    Args:
        dataframe: DataFrame to validate.
        required_columns: Columns required by the calculation.
        dataframe_name: Name used in validation error messages.

    Raises:
        ValueError: If required columns are missing or fixture IDs are
            duplicated.
    """
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


def calculate_expected_scores(
    strength_multipliers: pd.DataFrame,
    scoring_factors: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate expected home and away points for each fixture.

    Expected home points are calculated as:

        league average points
        × home attack multiplier
        × away defence multiplier
        × home scoring factor

    Expected away points are calculated as:

        league average points
        × away attack multiplier
        × home defence multiplier
        × away scoring factor

    A defence multiplier above one represents a weaker defence that concedes
    more points than average. It therefore increases the opponent's expected
    score.

    Args:
        strength_multipliers: One row per fixture containing the pre-match
            attack and defence multipliers for both teams.
        scoring_factors: One row per fixture containing the historical league
            average and venue scoring factors.

    Returns:
        One row per fixture containing expected home points, expected away
        points, expected margin and expected total points.

    Raises:
        ValueError: If inputs are invalid, fixtures cannot be matched, or
            model features contain missing or non-positive values.
    """
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

    expected_scores = strength_multipliers.merge(
        scoring_factors,
        on="fixture_id",
        how="left",
        validate="one_to_one",
    )

    model_feature_columns = [
        "home_attack_multiplier",
        "home_defence_multiplier",
        "away_attack_multiplier",
        "away_defence_multiplier",
        "league_average_points",
        "home_scoring_factor",
        "away_scoring_factor",
    ]

    missing_features = expected_scores[model_feature_columns].isna().any(axis=1)

    if missing_features.any():
        missing_fixture_ids = (
            expected_scores.loc[missing_features, "fixture_id"].astype(str).tolist()
        )
        raise ValueError(f"Missing model features for fixtures: {missing_fixture_ids}")

    non_positive_features = (expected_scores[model_feature_columns] <= 0).any(axis=1)

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

    return expected_scores[EXPECTED_SCORE_COLUMNS]
