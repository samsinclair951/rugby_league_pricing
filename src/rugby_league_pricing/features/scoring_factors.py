"""Calculate historical league and venue scoring factors."""

from __future__ import annotations

import pandas as pd

REQUIRED_RESULT_COLUMNS = {
    "fixture_id",
    "match_date",
    "home_points",
    "away_points",
}


def validate_results(results: pd.DataFrame) -> None:
    """Validate the results required for scoring-factor calculation.

    Args:
        results: Historical fixture results.

    Raises:
        ValueError: If required columns are missing, results are empty, or
            points columns contain invalid values.
    """
    missing_columns = REQUIRED_RESULT_COLUMNS.difference(results.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Results are missing required columns: {missing}")

    if results.empty:
        raise ValueError("Results cannot be empty.")

    if results["fixture_id"].duplicated().any():
        duplicate_fixture_ids = (
            results.loc[results["fixture_id"].duplicated(), "fixture_id"]
            .astype(str)
            .tolist()
        )
        raise ValueError(
            f"Results contain duplicate fixture IDs: {duplicate_fixture_ids}"
        )

    points_columns = ["home_points", "away_points"]

    if results[points_columns].isna().any().any():
        raise ValueError("Completed results cannot contain missing points.")

    if (results[points_columns] < 0).any().any():
        raise ValueError("Points cannot be negative.")


def calculate_historical_scoring_factors(
    results: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate league-average and home/away scoring factors by fixture.

    The factors for each fixture are calculated using results from earlier
    match dates only. All fixtures on the same date therefore receive the
    same pre-match factors, preventing matches played earlier in the input
    ordering from leaking into other fixtures on that date.

    League-average points represents the historical average points scored
    by one team per match.

    Args:
        results: Historical completed fixtures.

    Returns:
        One row per fixture containing:

        - fixture_id
        - league_average_points
        - home_scoring_factor
        - away_scoring_factor

        Fixtures on the first available match date will contain missing
        factors because no previous results exist.
    """
    validate_results(results)

    scoring = results[
        [
            "fixture_id",
            "match_date",
            "home_points",
            "away_points",
        ]
    ].copy()

    scoring["match_date"] = pd.to_datetime(
        scoring["match_date"],
        errors="raise",
    ).dt.normalize()

    daily_scoring = (
        scoring.groupby("match_date", as_index=False)
        .agg(
            matches_played=("fixture_id", "count"),
            home_points_scored=("home_points", "sum"),
            away_points_scored=("away_points", "sum"),
        )
        .sort_values("match_date")
        .reset_index(drop=True)
    )

    daily_scoring["previous_matches"] = (
        daily_scoring["matches_played"].cumsum().shift(1)
    )

    daily_scoring["previous_home_points"] = (
        daily_scoring["home_points_scored"].cumsum().shift(1)
    )

    daily_scoring["previous_away_points"] = (
        daily_scoring["away_points_scored"].cumsum().shift(1)
    )

    previous_total_points = (
        daily_scoring["previous_home_points"] + daily_scoring["previous_away_points"]
    )

    daily_scoring["league_average_points"] = previous_total_points / (
        daily_scoring["previous_matches"] * 2
    )

    historical_home_average = (
        daily_scoring["previous_home_points"] / daily_scoring["previous_matches"]
    )

    historical_away_average = (
        daily_scoring["previous_away_points"] / daily_scoring["previous_matches"]
    )

    daily_scoring["home_scoring_factor"] = (
        historical_home_average / daily_scoring["league_average_points"]
    )

    daily_scoring["away_scoring_factor"] = (
        historical_away_average / daily_scoring["league_average_points"]
    )

    factors_by_date = daily_scoring[
        [
            "match_date",
            "league_average_points",
            "home_scoring_factor",
            "away_scoring_factor",
        ]
    ]

    return (
        scoring[["fixture_id", "match_date"]]
        .merge(
            factors_by_date,
            on="match_date",
            how="left",
            validate="many_to_one",
        )
        .drop(columns="match_date")
    )
