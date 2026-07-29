"""Upsert helpers for strength-multiplier rows."""

from __future__ import annotations

import sqlite3

import pandas as pd

from rugby_league_pricing.utils.sql import upsert_dataframe

UPSERT_COLUMNS = [
    "fixture_id",
    "team_id",
    "opponent_id",
    "is_home",
    "match_date",
    "season",
    "league_average_points",
    "attack_multiplier",
    "defence_multiplier",
]


def upsert_strength_multipliers(
    connection: sqlite3.Connection,
    strength_multipliers: pd.DataFrame,
) -> int:
    """Insert or update pre-match strength multipliers."""
    if strength_multipliers.empty:
        return 0

    missing_columns = set(UPSERT_COLUMNS).difference(strength_multipliers.columns)

    if missing_columns:
        raise ValueError(
            "Strength multipliers are missing required columns: "
            f"{sorted(missing_columns)}"
        )

    duplicate_rows = strength_multipliers.duplicated(subset=["fixture_id", "team_id"])

    if duplicate_rows.any():
        duplicates = strength_multipliers.loc[
            duplicate_rows,
            ["fixture_id", "team_id"],
        ].to_dict(orient="records")

        raise ValueError(
            f"Strength multipliers contain duplicate fixture/team rows: {duplicates}"
        )

    return upsert_dataframe(
        connection=connection,
        dataframe=strength_multipliers,
        table_name="strength_multipliers",
        columns=UPSERT_COLUMNS,
        conflict_columns=["fixture_id", "team_id"],
        update_timestamp=True,
    )
