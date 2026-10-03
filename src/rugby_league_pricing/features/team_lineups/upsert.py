"""Upsert helpers for expected-team-lineup rows."""

from __future__ import annotations

import sqlite3

import pandas as pd

from rugby_league_pricing.utils.sql import upsert_dataframe

UPSERT_COLUMNS = [
    "fixture_id",
    "team_id",
    "player_id",
    "player_name",
    "position_id",
    "version_type",
    "notes",
]


def upsert_expected_team_lineups(
    connection: sqlite3.Connection,
    lineups: pd.DataFrame,
) -> int:
    """Insert or update expected-team-lineup rows.

    Each row represents a single player in an expected or confirmed lineup for a
    fixture, tagged with the version_type that reflects the source of information
    (e.g. 'pre_preview_expected_line_up', 'confirmed_line_up').
    """
    if lineups.empty:
        return 0

    missing_columns = set(UPSERT_COLUMNS).difference(lineups.columns)

    if missing_columns:
        raise ValueError(
            "Expected team lineups are missing required columns: "
            f"{sorted(missing_columns)}"
        )

    duplicate_rows = lineups.duplicated(
        subset=["fixture_id", "team_id", "player_id", "version_type"]
    )

    if duplicate_rows.any():
        duplicates = lineups.loc[
            duplicate_rows,
            ["fixture_id", "team_id", "player_id", "version_type"],
        ].to_dict(orient="records")

        raise ValueError(
            "Expected team lineups contain duplicate fixture/team/player/version rows: "
            f"{duplicates}"
        )

    return upsert_dataframe(
        connection=connection,
        dataframe=lineups,
        table_name="expected_team_lineups",
        columns=UPSERT_COLUMNS,
        conflict_columns=["fixture_id", "team_id", "player_id", "version_type"],
        update_timestamp=True,
    )
