"""Core scoring-factor calculation helpers."""

from __future__ import annotations

import pandas as pd

from .constants import REQUIRED_RESULT_COLUMNS


def validate_results(results: pd.DataFrame) -> None:
    """Validate the results required for scoring-factor calculation."""
    _validate_required_columns(results)
    _validate_fixture_ids(results)
    _validate_points(results)


def _validate_required_columns(results: pd.DataFrame) -> None:
    """Ensure the input contains all required result columns."""
    missing_columns = REQUIRED_RESULT_COLUMNS.difference(results.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Results are missing required columns: {missing}")


def _validate_fixture_ids(results: pd.DataFrame) -> None:
    """Ensure the results are non-empty and fixture IDs are unique."""
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


def _validate_points(results: pd.DataFrame) -> None:
    """Ensure completed results contain valid point totals."""
    points_columns = ["home_points", "away_points"]

    if results[points_columns].isna().any().any():
        raise ValueError("Completed results cannot contain missing points.")

    if (results[points_columns] < 0).any().any():
        raise ValueError("Points cannot be negative.")


def _prepare_scoring_data(results: pd.DataFrame) -> pd.DataFrame:
    """Select the required columns and normalise match dates."""
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

    return scoring


def _calculate_daily_scoring(scoring: pd.DataFrame) -> pd.DataFrame:
    """Aggregate scoring totals by match date and compute rolling averages."""
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

    return daily_scoring


def _build_factors_by_date(daily_scoring: pd.DataFrame) -> pd.DataFrame:
    """Select the factor columns required for the final output."""
    return daily_scoring[
        [
            "match_date",
            "league_average_points",
            "home_scoring_factor",
            "away_scoring_factor",
        ]
    ]


def _merge_factors_to_scoring(
    scoring: pd.DataFrame,
    factors_by_date: pd.DataFrame,
) -> pd.DataFrame:
    """Attach the pre-match factors to each fixture by match date."""
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


def calculate_historical_scoring_factors(
    results: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate league-average and home/away scoring factors by fixture."""
    validate_results(results)

    scoring = _prepare_scoring_data(results)
    daily_scoring = _calculate_daily_scoring(scoring)
    factors_by_date = _build_factors_by_date(daily_scoring)

    return _merge_factors_to_scoring(scoring, factors_by_date)
