"""Persist team-selection player adjustments."""

from __future__ import annotations

import sqlite3

import pandas as pd


COLUMNS = [
    "fixture_id",
    "team_id",
    "opponent_id",
    "is_home",
    "version_type",

    "reference_attack_strength",
    "selected_attack_strength",
    "attack_selection_gap",

    "reference_defence_strength",
    "selected_defence_strength",
    "defence_selection_gap",

    "player_attack_signal",
    "player_defence_signal",
    "player_strength_signal",
    "top5_strength_on_field",

    "props_8_10_strength",
    "middle_pack_8_10_11_12_13_strength",
    "halves_6_7_strength",
    "spine_1_6_7_9_strength",
    "combo_1_7_strength",
    "combo_1_6_strength",
    "hooker_9_strength",
    "stand_off_6_strength",
    "scrum_half_7_strength",

    "missing_core_count",
    "missing_core_overall_sum",
    "missing_core_top3_sum",

    "missing_props_8_10_sum",
    "missing_middle_pack_8_10_11_12_13_sum",
    "missing_halves_6_7_sum",
    "missing_spine_1_6_7_9_sum",
    "missing_combo_1_7_sum",
    "missing_combo_1_6_sum",
    "missing_hooker_9_sum",
    "missing_stand_off_6_sum",
    "missing_scrum_half_7_sum",

    "player_log_adjustment",
    "score_adjustment_factor",
    "model_version",
]


def upsert_team_selection_adjustments(
    connection: sqlite3.Connection,
    adjustments: pd.DataFrame,
) -> int:
    """Insert or update team-selection adjustment rows."""
    if adjustments.empty:
        return 0

    frame = adjustments.copy()

    # Allow diagnostic columns to be absent while we're
    # still building out the player model.
    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    frame = frame[COLUMNS]

    insert_columns = ",\n        ".join(COLUMNS)
    placeholders = ", ".join(["?"] * len(COLUMNS))

    update_columns = [
        column
        for column in COLUMNS
        if column not in {
            "fixture_id",
            "team_id",
            "version_type",
        }
    ]

    update_clause = ",\n        ".join(
        f"{column} = excluded.{column}"
        for column in update_columns
    )

    sql = f"""
        INSERT INTO team_selection_adjustments (
            {insert_columns}
        )
        VALUES (
            {placeholders}
        )

        ON CONFLICT (
            fixture_id,
            team_id,
            version_type
        )
        DO UPDATE SET
            {update_clause},
            updated_at = CURRENT_TIMESTAMP
    """
    rows = [
            tuple(
                None if pd.isna(value) else value
                for value in row
            )
            for row in frame.itertuples(
                index=False,
                name=None,
            )
        ]

    connection.executemany(
        sql,
        rows,
    )

    return len(rows)