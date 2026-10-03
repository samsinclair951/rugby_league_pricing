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
    "version_type",
    "league_average_points",
    "raw_attack_multiplier",
    "raw_defence_multiplier",
    "attack_multiplier",
    "defence_multiplier",
    "scaled_attack_multiplier",
    "scaled_defence_multiplier",
]

DEFAULT_VERSION_TYPE = "baseline"


def upsert_strength_multipliers(
    connection: sqlite3.Connection,
    strength_multipliers: pd.DataFrame,
    version_type: str = DEFAULT_VERSION_TYPE,
) -> int:
    """Insert or update pre-match strength multipliers.

    version_type controls which lineup state these multipliers represent:
      'baseline'                    – form-only, no lineup information
      'pre_preview_expected_line_up' – early-week expected team
      'preview_expected_line_up'    – updated after preview released
      'confirmed_line_up'           – final confirmed team selection
    """
    if strength_multipliers.empty:
        return 0

    strength_multipliers = strength_multipliers.copy()
    if "version_type" not in strength_multipliers.columns:
        strength_multipliers["version_type"] = version_type

    missing_columns = set(UPSERT_COLUMNS).difference(strength_multipliers.columns)

    if missing_columns:
        raise ValueError(
            "Strength multipliers are missing required columns: "
            f"{sorted(missing_columns)}"
        )

    duplicate_rows = strength_multipliers.duplicated(
        subset=["fixture_id", "team_id", "version_type"]
    )

    if duplicate_rows.any():
        duplicates = strength_multipliers.loc[
            duplicate_rows,
            ["fixture_id", "team_id", "version_type"],
        ].to_dict(orient="records")

        raise ValueError(
            f"Strength multipliers contain duplicate fixture/team/version rows: {duplicates}"
        )

    return upsert_dataframe(
        connection=connection,
        dataframe=strength_multipliers,
        table_name="strength_multipliers",
        columns=UPSERT_COLUMNS,
        conflict_columns=["fixture_id", "team_id", "version_type"],
        update_timestamp=True,
    )
