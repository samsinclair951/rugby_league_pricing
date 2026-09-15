from __future__ import annotations

import sqlite3

from rugby_league_pricing.features.players import build_full_strength_reference


def test_build_full_strength_reference_tracks_selection_gap() -> None:
    connection = sqlite3.connect(":memory:")

    try:
        connection.execute(
            """
            CREATE TABLE fixtures (
                fixture_id TEXT PRIMARY KEY,
                match_date TEXT,
                season INTEGER,
                home_team_id INTEGER,
                away_team_id INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE player_ratings (
                player_rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
                fixture_id TEXT NOT NULL,
                team_id INTEGER NOT NULL,
                player_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                position_id INTEGER,
                season INTEGER NOT NULL,
                attack_rating REAL NOT NULL,
                defence_rating REAL NOT NULL,
                overall_rating REAL NOT NULL,
                reliability REAL NOT NULL
            )
            """
        )

        fixture_rows = [
            ("f_1", "2026-01-01", 2026, 1, 2),
            ("f_2", "2026-01-08", 2026, 1, 2),
            ("f_3", "2026-01-15", 2026, 1, 2),
            ("f_4", "2026-01-22", 2026, 1, 2),
        ]
        connection.executemany(
            "INSERT INTO fixtures (fixture_id, match_date, season, home_team_id, away_team_id) VALUES (?, ?, ?, ?, ?)",
            fixture_rows,
        )

        player_rows = [
            ("f_1", 1, "p_a", "Alpha", 1, 2026, 10.0, 5.0, 15.0, 1.0),
            ("f_1", 1, "p_b", "Bravo", 7, 2026, 8.0, 8.0, 16.0, 1.0),
            ("f_1", 1, "p_c", "Charlie", 6, 2026, 9.0, 6.0, 15.0, 1.0),
            ("f_2", 1, "p_a", "Alpha", 1, 2026, 10.0, 5.0, 15.0, 1.0),
            ("f_2", 1, "p_d", "Delta", 7, 2026, 11.0, 7.0, 18.0, 1.0),
            ("f_2", 1, "p_c", "Charlie", 6, 2026, 9.0, 6.0, 15.0, 1.0),
            ("f_3", 1, "p_a", "Alpha", 1, 2026, 10.0, 5.0, 15.0, 1.0),
            ("f_3", 1, "p_d", "Delta", 7, 2026, 11.0, 7.0, 18.0, 1.0),
            ("f_3", 1, "p_e", "Echo", 6, 2026, 12.0, 8.0, 20.0, 1.0),
            ("f_4", 1, "p_a", "Alpha", 1, 2026, 9.0, 5.0, 14.0, 1.0),
            ("f_4", 1, "p_d", "Delta", 7, 2026, 11.0, 7.0, 18.0, 1.0),
            ("f_4", 1, "p_e", "Echo", 6, 2026, 12.0, 8.0, 20.0, 1.0),
        ]
        connection.executemany(
            """
            INSERT INTO player_ratings (
                fixture_id, team_id, player_id, player_name, position_id, season,
                attack_rating, defence_rating, overall_rating, reliability
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            player_rows,
        )

        reference = build_full_strength_reference(
            connection=connection,
            fixture_ids=["f_4"],
            window=3,
        )

        assert not reference.empty
        assert reference["team_id"].tolist() == [1]
        assert reference["fixture_id"].tolist() == ["f_4"]
        assert reference["full_strength_value"].iloc[0] > 0
        assert reference["selection_gap"].iloc[0] >= 0

    finally:
        connection.close()
