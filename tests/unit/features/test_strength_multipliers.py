from __future__ import annotations

import sqlite3

import pandas as pd

from rugby_league_pricing.features.strength_multipliers import (
    upsert_strength_multipliers,
)


def test_upsert_strength_multipliers_round_trip() -> None:
    """Strength multipliers should be saved to SQLite correctly."""
    connection = sqlite3.connect(":memory:")

    try:
        connection.execute(
            """
            CREATE TABLE strength_multipliers (
                strength_multiplier_id INTEGER PRIMARY KEY AUTOINCREMENT,

                fixture_id TEXT NOT NULL,
                team_id INTEGER NOT NULL,
                opponent_id INTEGER NOT NULL,
                is_home INTEGER NOT NULL,

                match_date TEXT NOT NULL,
                season INTEGER NOT NULL,

                league_average_points REAL,
                raw_attack_multiplier REAL,
                raw_defence_multiplier REAL,
                attack_multiplier REAL,
                defence_multiplier REAL,
                scaled_attack_multiplier REAL,
                scaled_defence_multiplier REAL,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                UNIQUE (
                    fixture_id,
                    team_id
                )
            )
            """
        )

        strength_multipliers = pd.DataFrame(
            {
                "fixture_id": ["fixture_1", "fixture_1"],
                "team_id": [1, 2],
                "opponent_id": [2, 1],
                "is_home": [1, 0],
                "match_date": [
                    pd.Timestamp("2026-01-01"),
                    pd.Timestamp("2026-01-01"),
                ],
                "season": [2026, 2026],
                "league_average_points": [24.0, 24.0],
                "raw_attack_multiplier": [1.12, 0.88],
                "raw_defence_multiplier": [0.94, 1.06],
                "attack_multiplier": [1.10, 0.90],
                "defence_multiplier": [0.95, 1.05],
                "scaled_attack_multiplier": [1.08, 0.92],
                "scaled_defence_multiplier": [0.96, 1.04],
            }
        )

        rows_saved = upsert_strength_multipliers(
            connection=connection,
            strength_multipliers=strength_multipliers,
        )

        assert rows_saved == 2

        rows = connection.execute(
            """
            SELECT
                fixture_id,
                team_id,
                opponent_id,
                is_home,
                match_date,
                season,
                league_average_points,
                attack_multiplier,
                defence_multiplier
            FROM strength_multipliers
            ORDER BY team_id
            """
        ).fetchall()

        assert rows == [
            (
                "fixture_1",
                1,
                2,
                1,
                "2026-01-01",
                2026,
                24.0,
                1.1,
                0.95,
            ),
            (
                "fixture_1",
                2,
                1,
                0,
                "2026-01-01",
                2026,
                24.0,
                0.9,
                1.05,
            ),
        ]

    finally:
        connection.close()
