from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from rugby_league_pricing.features.team_lineups.build_expected import (
    build_expected_lineups_for_match_date,
)
from rugby_league_pricing.utils.sql import upsert_dataframe
from scripts.features.rebuild_team_selection_adjustments import (
    load_fixtures,
    rebuild_team_selection_adjustments,
)


def test_upsert_dataframe_updates_lineup_order() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE teamsheets (
            fixture_id TEXT NOT NULL,
            team_id INTEGER NOT NULL,
            player_id TEXT NOT NULL,
            lineup_order INTEGER NOT NULL,
            PRIMARY KEY (fixture_id, team_id, player_id)
        )
        """
    )

    frame = pd.DataFrame(
        [
            {
                "fixture_id": "fx-1",
                "team_id": 1,
                "player_id": "p-1",
                "lineup_order": 18,
            }
        ]
    )

    saved = upsert_dataframe(
        connection=connection,
        dataframe=frame,
        table_name="teamsheets",
        columns=[
            "fixture_id",
            "team_id",
            "player_id",
            "lineup_order",
        ],
        conflict_columns=["fixture_id", "team_id", "player_id"],
        update_columns=["lineup_order"],
        update_timestamp=False,
    )

    assert saved == 1

    updated = frame.copy()
    updated["lineup_order"] = 17

    upsert_dataframe(
        connection=connection,
        dataframe=updated,
        table_name="teamsheets",
        columns=[
            "fixture_id",
            "team_id",
            "player_id",
            "lineup_order",
        ],
        conflict_columns=["fixture_id", "team_id", "player_id"],
        update_columns=["lineup_order"],
        update_timestamp=False,
    )

    row = connection.execute(
        """
        SELECT lineup_order
        FROM teamsheets
        WHERE fixture_id = 'fx-1'
          AND team_id = 1
          AND player_id = 'p-1'
        """
    ).fetchone()

    assert row == (17,)


def test_build_expected_lineups_for_match_date_keeps_lineup_order_18() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE fixtures (
            fixture_id TEXT PRIMARY KEY,
            match_date TEXT NOT NULL,
            home_team_id INTEGER NOT NULL,
            away_team_id INTEGER NOT NULL
        );

        CREATE TABLE players (
            player_id TEXT NOT NULL,
            player_name TEXT NOT NULL,
            season INTEGER NOT NULL,
            team_id INTEGER NOT NULL
        );

        CREATE TABLE teamsheets (
            fixture_id TEXT NOT NULL,
            team_id INTEGER NOT NULL,
            player_id TEXT NOT NULL,
            position TEXT,
            lineup_order INTEGER NOT NULL
        );
        """
    )

    connection.executemany(
        "INSERT INTO fixtures VALUES (?, ?, ?, ?)",
        [
            ("prev-fixture", "2026-09-12 17:30:00", 1, 2),
            ("target-fixture", "2026-09-13 17:30:00", 1, 2),
        ],
    )

    connection.executemany(
        "INSERT INTO players VALUES (?, ?, ?, ?)",
        [
            ("home-1", "Home One", 2026, 1),
            ("home-2", "Home Two", 2026, 1),
            ("home-18", "Home Reserve", 2026, 1),
            ("away-1", "Away One", 2026, 2),
            ("away-2", "Away Two", 2026, 2),
            ("away-18", "Away Reserve", 2026, 2),
        ],
    )

    connection.executemany(
        """
        INSERT INTO teamsheets (
            fixture_id,
            team_id,
            player_id,
            position,
            lineup_order
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("prev-fixture", 1, "home-1", "1", 1),
            ("prev-fixture", 1, "home-2", "2", 2),
            ("prev-fixture", 1, "home-18", "17", 18),
            ("prev-fixture", 2, "away-1", "1", 1),
            ("prev-fixture", 2, "away-2", "2", 2),
            ("prev-fixture", 2, "away-18", "17", 18),
        ],
    )

    lineup = build_expected_lineups_for_match_date(
        connection=connection,
        match_date="2026-09-13",
    )

    assert len(lineup) == 6
    assert set(lineup["fixture_id"]) == {"target-fixture"}
    assert set(lineup["player_id"]) == {
        "home-1",
        "home-2",
        "home-18",
        "away-1",
        "away-2",
        "away-18",
    }
    assert lineup["position_id"].isna().sum() == 0


def test_load_fixtures_uses_requested_date_range_not_hardcoded_2026() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE fixtures (
            fixture_id TEXT PRIMARY KEY,
            match_date TEXT NOT NULL,
            season INTEGER NOT NULL,
            home_team_id INTEGER NOT NULL,
            away_team_id INTEGER NOT NULL
        );

        CREATE TABLE results (
            fixture_id TEXT PRIMARY KEY,
            result TEXT NOT NULL
        );

        CREATE TABLE teamsheets (
            fixture_id TEXT NOT NULL,
            team_id INTEGER NOT NULL,
            player_id TEXT NOT NULL,
            lineup_order INTEGER NOT NULL,
            PRIMARY KEY (fixture_id, team_id, player_id)
        );
        """
    )

    connection.executemany(
        "INSERT INTO fixtures VALUES (?, ?, ?, ?, ?)",
        [
            ("fx-2024", "2024-06-02 15:00:00", 2024, 1, 2),
            ("fx-2026", "2026-10-01 15:00:00", 2026, 3, 4),
        ],
    )

    connection.executemany(
        "INSERT INTO results VALUES (?, ?)",
        [
            ("fx-2024", "1-0"),
            ("fx-2026", "2-1"),
        ],
    )

    connection.executemany(
        "INSERT INTO teamsheets VALUES (?, ?, ?, ?)",
        [
            ("fx-2024", 1, "p1", 1),
            ("fx-2024", 1, "p2", 2),
            ("fx-2024", 2, "p3", 1),
            ("fx-2024", 2, "p4", 2),
            ("fx-2026", 3, "p5", 1),
            ("fx-2026", 3, "p6", 2),
            ("fx-2026", 4, "p7", 1),
            ("fx-2026", 4, "p8", 2),
        ],
    )

    fixtures = load_fixtures(
        connection,
        version_type="confirmed_line_up",
        start_date="2024-01-01",
        end_date="2025-12-31",
    )

    assert fixtures["fixture_id"].tolist() == ["fx-2024"]


def test_rebuild_team_selection_adjustments_processes_fixture_even_when_rows_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = sqlite3.connect(":memory:")

    monkeypatch.setattr(
        "scripts.features.rebuild_team_selection_adjustments.load_fixtures",
        lambda connection, version_type, start_date=None, end_date=None: pd.DataFrame(
            [
                {
                    "fixture_id": "fx-1",
                    "match_date": pd.Timestamp("2026-09-13"),
                    "season": 2026,
                    "tournament_id": 1,
                    "home_team_id": 1,
                    "away_team_id": 2,
                    "round_number": 24,
                    "round_start_date": pd.Timestamp("2026-09-10"),
                    "round_end_date": pd.Timestamp("2026-09-13"),
                }
            ]
        ),
    )

    build_calls: list[str] = []
    upsert_calls: list[int] = []

    monkeypatch.setattr(
        "scripts.features.rebuild_team_selection_adjustments.build_fixture_adjustments",
        lambda connection, fixture, version_type: build_calls.append(
            str(fixture["fixture_id"])
        )
        or pd.DataFrame(
            [
                {
                    "fixture_id": "fx-1",
                    "team_id": 1,
                    "version_type": version_type,
                },
                {
                    "fixture_id": "fx-1",
                    "team_id": 2,
                    "version_type": version_type,
                },
            ]
        ),
    )

    monkeypatch.setattr(
        "scripts.features.rebuild_team_selection_adjustments.upsert_team_selection_adjustments",
        lambda connection, adjustments: upsert_calls.append(len(adjustments)) or len(adjustments),
    )

    rebuild_team_selection_adjustments(
        connection=connection,
        version_type="pre_preview_expected_line_up",
    )

    assert build_calls == ["fx-1"]
    assert upsert_calls == [2]
