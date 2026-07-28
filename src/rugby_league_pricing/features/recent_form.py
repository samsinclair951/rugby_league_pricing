from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any

import pandas as pd

RESULTS_SOURCE = "rugby_league_project"
DEFAULT_WINDOWS = (5, 10)

RESULTS_QUERY = """
    SELECT
        fixture_id,
        season,
        match_date,
        home_team_id,
        home_score,
        away_team_id,
        away_score
    FROM results
    WHERE source_name = ?
      AND home_score IS NOT NULL
      AND away_score IS NOT NULL
    ORDER BY
        match_date,
        fixture_id
"""


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


def stack_results(
    results: pd.DataFrame,
) -> pd.DataFrame:
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

    team_matches = pd.concat(
        [home_rows, away_rows],
        ignore_index=True,
    )

    team_matches["margin"] = team_matches["points_for"] - team_matches["points_against"]

    return team_matches.sort_values(
        [
            "team_id",
            "match_date",
            "fixture_id",
        ]
    ).reset_index(drop=True)


def add_recent_form(
    team_matches: pd.DataFrame,
    windows: Sequence[int] = DEFAULT_WINDOWS,
) -> pd.DataFrame:
    """Add pre-match rolling attack, defence and margin features."""
    recent_form = team_matches.sort_values(
        [
            "team_id",
            "match_date",
            "fixture_id",
        ]
    ).copy()

    grouped = recent_form.groupby(
        "team_id",
        sort=False,
    )

    recent_form["history_games_before"] = grouped.cumcount()

    for window in windows:
        if window <= 0:
            raise ValueError(f"Rolling windows must be positive: {window}")

        recent_form[f"recent_points_for_{window}"] = grouped["points_for"].transform(
            lambda values: (
                values.shift(1)
                .rolling(
                    window=window,
                    min_periods=1,
                )
                .mean()
            )
        )

        recent_form[f"recent_points_against_{window}"] = grouped[
            "points_against"
        ].transform(
            lambda values: (
                values.shift(1)
                .rolling(
                    window=window,
                    min_periods=1,
                )
                .mean()
            )
        )

        recent_form[f"recent_margin_{window}"] = grouped["margin"].transform(
            lambda values: (
                values.shift(1)
                .rolling(
                    window=window,
                    min_periods=1,
                )
                .mean()
            )
        )

        recent_form[f"recent_games_used_{window}"] = (
            grouped["points_for"]
            .transform(
                lambda values: (
                    values.shift(1)
                    .rolling(
                        window=window,
                        min_periods=1,
                    )
                    .count()
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
    results = load_results(
        connection=connection,
    )

    team_matches = stack_results(
        results=results,
    )

    return add_recent_form(
        team_matches=team_matches,
        windows=windows,
    )


def prepare_database_rows(
    recent_form: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Convert pandas values into values supported by SQLite."""
    rows: list[dict[str, Any]] = []

    for record in recent_form.to_dict(orient="records"):
        prepared_record: dict[str, Any] = {}

        for column, value in record.items():
            if pd.isna(value):
                prepared_record[column] = None
            elif isinstance(value, pd.Timestamp):
                prepared_record[column] = value.date().isoformat()
            elif hasattr(value, "item"):
                prepared_record[column] = value.item()
            else:
                prepared_record[column] = value

        rows.append(prepared_record)

    return rows


def save_recent_form(
    connection: sqlite3.Connection,
    recent_form: pd.DataFrame,
) -> int:
    """Insert or update recent-form rows."""
    if recent_form.empty:
        return 0

    required_windows = set(DEFAULT_WINDOWS)

    missing_windows = {
        window
        for window in required_windows
        if f"recent_margin_{window}" not in recent_form.columns
    }

    if missing_windows:
        raise ValueError(
            f"Recent form is missing required windows: {sorted(missing_windows)}"
        )

    rows = prepare_database_rows(
        recent_form=recent_form,
    )

    sql = """
        INSERT INTO recent_form (
            fixture_id,
            team_id,
            opponent_id,
            is_home,
            match_date,
            season,
            points_for,
            points_against,
            margin,
            history_games_before,
            recent_points_for_5,
            recent_points_against_5,
            recent_margin_5,
            recent_games_used_5,
            recent_points_for_10,
            recent_points_against_10,
            recent_margin_10,
            recent_games_used_10
        )
        VALUES (
            :fixture_id,
            :team_id,
            :opponent_id,
            :is_home,
            :match_date,
            :season,
            :points_for,
            :points_against,
            :margin,
            :history_games_before,
            :recent_points_for_5,
            :recent_points_against_5,
            :recent_margin_5,
            :recent_games_used_5,
            :recent_points_for_10,
            :recent_points_against_10,
            :recent_margin_10,
            :recent_games_used_10
        )
        ON CONFLICT (
            fixture_id,
            team_id
        )
        DO UPDATE SET
            opponent_id = excluded.opponent_id,
            is_home = excluded.is_home,
            match_date = excluded.match_date,
            season = excluded.season,
            points_for = excluded.points_for,
            points_against = excluded.points_against,
            margin = excluded.margin,
            history_games_before = excluded.history_games_before,
            recent_points_for_5 = excluded.recent_points_for_5,
            recent_points_against_5 =
                excluded.recent_points_against_5,
            recent_margin_5 = excluded.recent_margin_5,
            recent_games_used_5 =
                excluded.recent_games_used_5,
            recent_points_for_10 =
                excluded.recent_points_for_10,
            recent_points_against_10 =
                excluded.recent_points_against_10,
            recent_margin_10 = excluded.recent_margin_10,
            recent_games_used_10 =
                excluded.recent_games_used_10,
            updated_at = CURRENT_TIMESTAMP
    """

    connection.executemany(
        sql,
        rows,
    )

    return len(rows)


def rebuild_recent_form(
    connection: sqlite3.Connection,
) -> int:
    """Recalculate and upsert all recent-form rows."""
    recent_form = build_recent_form(
        connection=connection,
    )

    return save_recent_form(
        connection=connection,
        recent_form=recent_form,
    )
