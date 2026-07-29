"""Upsert helpers for recent-form rows."""

from __future__ import annotations

import sqlite3

import pandas as pd

from rugby_league_pricing.utils.sql import upsert_dataframe

from .core import build_recent_form
from .constants import DEFAULT_WINDOWS


def upsert_recent_form(
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

    columns = [
        "fixture_id",
        "team_id",
        "opponent_id",
        "is_home",
        "match_date",
        "season",
        "points_for",
        "points_against",
        "margin",
        "history_games_before",
        "recent_points_for_5",
        "recent_points_against_5",
        "recent_margin_5",
        "recent_games_used_5",
        "recent_points_for_10",
        "recent_points_against_10",
        "recent_margin_10",
        "recent_games_used_10",
    ]

    missing_columns = set(columns).difference(recent_form.columns)

    if missing_columns:
        raise ValueError(
            f"Recent form is missing required columns: {sorted(missing_columns)}"
        )

    duplicate_rows = recent_form.duplicated(subset=["fixture_id", "team_id"])

    if duplicate_rows.any():
        duplicates = recent_form.loc[
            duplicate_rows,
            ["fixture_id", "team_id"],
        ].to_dict(orient="records")

        raise ValueError(
            f"Recent form contains duplicate fixture/team rows: {duplicates}"
        )

    return upsert_dataframe(
        connection=connection,
        dataframe=recent_form,
        table_name="recent_form",
        columns=columns,
        conflict_columns=["fixture_id", "team_id"],
        update_timestamp=True,
    )

def rebuild_recent_form(
    connection: sqlite3.Connection,
) -> int:
    """Recalculate and upsert all recent-form rows."""
    recent_form = build_recent_form(
        connection=connection,
    )
    return upsert_recent_form(
        connection=connection,
        recent_form=recent_form,
    )