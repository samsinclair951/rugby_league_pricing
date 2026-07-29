"""Core recent-form calculation helpers."""

from typing import Sequence

import sqlite3

import pandas as pd

from .constants import DEFAULT_WINDOWS, RESULTS_QUERY, RESULTS_SOURCE


def load_results(
    connection: sqlite3.Connection,
    source_name: str = RESULTS_SOURCE,
) -> pd.DataFrame:
    """Load completed results needed to build recent-form features."""
    results = pd.read_sql_query(
        RESULTS_QUERY,
        connection,
        params=(source_name,),
    )

    if results.empty:
        raise ValueError(f"No completed results found for source {source_name!r}")

    results["match_date"] = pd.to_datetime(
        results["match_date"],
        errors="raise",
    )

    integer_columns = [
        "season",
        "home_team_id",
        "home_score",
        "away_team_id",
        "away_score",
    ]

    results[integer_columns] = results[integer_columns].astype(int)

    return results


def stack_results(results: pd.DataFrame) -> pd.DataFrame:
    """Convert each result into one performance row per team."""
    required_columns = {
        "fixture_id",
        "season",
        "match_date",
        "home_team_id",
        "home_score",
        "away_team_id",
        "away_score",
    }

    missing_columns = required_columns.difference(results.columns)

    if missing_columns:
        raise ValueError(f"Results are missing columns: {sorted(missing_columns)}")

    home_rows = pd.DataFrame(
        {
            "fixture_id": results["fixture_id"],
            "season": results["season"],
            "match_date": results["match_date"],
            "team_id": results["home_team_id"],
            "opponent_id": results["away_team_id"],
            "is_home": 1,
            "points_for": results["home_score"],
            "points_against": results["away_score"],
        }
    )

    away_rows = pd.DataFrame(
        {
            "fixture_id": results["fixture_id"],
            "season": results["season"],
            "match_date": results["match_date"],
            "team_id": results["away_team_id"],
            "opponent_id": results["home_team_id"],
            "is_home": 0,
            "points_for": results["away_score"],
            "points_against": results["home_score"],
        }
    )

    team_matches = pd.concat([home_rows, away_rows], ignore_index=True)
    team_matches["margin"] = team_matches["points_for"] - team_matches["points_against"]

    return team_matches.sort_values(
        ["team_id", "match_date", "fixture_id"]
    ).reset_index(drop=True)


def add_recent_form(
    team_matches: pd.DataFrame,
    windows: Sequence[int] = DEFAULT_WINDOWS,
) -> pd.DataFrame:
    """Add pre-match rolling attack, defence and margin features."""
    recent_form = team_matches.sort_values(
        ["team_id", "match_date", "fixture_id"]
    ).copy()

    grouped = recent_form.groupby("team_id", sort=False)
    recent_form["history_games_before"] = grouped.cumcount()

    for window in windows:
        if window <= 0:
            raise ValueError(f"Rolling windows must be positive: {window}")

        recent_form[f"recent_points_for_{window}"] = grouped["points_for"].transform(
            lambda values, window=window: (
                values.shift(1).rolling(window=window, min_periods=1).mean()
            )
        )

        recent_form[f"recent_points_against_{window}"] = grouped[
            "points_against"
        ].transform(
            lambda values, window=window: (
                values.shift(1).rolling(window=window, min_periods=1).mean()
            )
        )

        recent_form[f"recent_margin_{window}"] = grouped["margin"].transform(
            lambda values, window=window: (
                values.shift(1).rolling(window=window, min_periods=1).mean()
            )
        )

        recent_form[f"recent_games_used_{window}"] = (
            grouped["points_for"]
            .transform(
                lambda values, window=window: (
                    values.shift(1).rolling(window=window, min_periods=1).count()
                )
            )
            .astype("Int64")
        )

    return recent_form.reset_index(drop=True)


def build_recent_form(
    connection: sqlite3.Connection,
    windows: Sequence[int] = DEFAULT_WINDOWS,
) -> pd.DataFrame:
    """Load results and calculate recent-form features."""
    results = load_results(connection=connection)
    team_matches = stack_results(results=results)
    return add_recent_form(team_matches=team_matches, windows=windows)
