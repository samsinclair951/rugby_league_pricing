from __future__ import annotations

import sqlite3

import pandas as pd

from rugby_league_pricing.features.team_lineups.upsert import (
    upsert_expected_team_lineups,
)


VERSION_TYPE = "pre_preview_expected_line_up"


def build_expected_lineup_from_previous_teamsheet(
    connection: sqlite3.Connection,
    fixture_id: str,
    team_id: int,
) -> pd.DataFrame:
    fixture = connection.execute(
        """
        SELECT match_date
        FROM fixtures
        WHERE fixture_id = ?
        """,
        (fixture_id,),
    ).fetchone()

    if fixture is None:
        raise ValueError(f"Unknown fixture_id: {fixture_id}")

    match_date = fixture[0]

    previous_fixture = connection.execute(
        """
        SELECT f.fixture_id
        FROM fixtures f
        JOIN teamsheets ts
            ON ts.fixture_id = f.fixture_id
           AND ts.team_id = ?
        WHERE (
            f.home_team_id = ?
            OR f.away_team_id = ?
        )
          AND f.match_date < ?
        GROUP BY f.fixture_id, f.match_date
        ORDER BY f.match_date DESC
        LIMIT 1
        """,
        (
            team_id,
            team_id,
            team_id,
            match_date,
        ),
    ).fetchone()

    if previous_fixture is None:
        raise ValueError(
            f"No previous teamsheet found for team_id={team_id}"
        )

    previous_fixture_id = str(previous_fixture[0])

    lineup = pd.read_sql_query(
        """
        SELECT
            ? AS fixture_id,
            ts.team_id,
            ts.player_id,
            p.player_name,
            CAST(ts.position AS INTEGER) AS position_id,
            ? AS version_type,
            ? AS notes
        FROM teamsheets ts
        LEFT JOIN players p
            ON p.player_id = ts.player_id
           AND p.season = (
                SELECT season
                FROM fixtures
                WHERE fixture_id = ?
           )
           AND p.team_id = ts.team_id
        WHERE ts.fixture_id = ?
          AND ts.team_id = ?
        ORDER BY ts.lineup_order
        """,
        connection,
        params=[
            fixture_id,
            VERSION_TYPE,
            f"Copied from previous teamsheet {previous_fixture_id}",
            fixture_id,
            previous_fixture_id,
            team_id,
        ],
    )

    return lineup


def build_expected_lineups_for_fixture(
    connection: sqlite3.Connection,
    fixture_id: str,
) -> pd.DataFrame:
    fixture = connection.execute(
        """
        SELECT home_team_id, away_team_id
        FROM fixtures
        WHERE fixture_id = ?
        """,
        (fixture_id,),
    ).fetchone()

    if fixture is None:
        raise ValueError(f"Unknown fixture_id: {fixture_id}")

    home_team_id, away_team_id = fixture

    frames = [
        build_expected_lineup_from_previous_teamsheet(
            connection=connection,
            fixture_id=fixture_id,
            team_id=int(home_team_id),
        ),
        build_expected_lineup_from_previous_teamsheet(
            connection=connection,
            fixture_id=fixture_id,
            team_id=int(away_team_id),
        ),
    ]

    return pd.concat(frames, ignore_index=True)


def save_expected_lineups_for_fixture(
    connection: sqlite3.Connection,
    fixture_id: str,
) -> int:
    lineups = build_expected_lineups_for_fixture(
        connection=connection,
        fixture_id=fixture_id,
    )

    connection.execute(
        """
        DELETE FROM expected_team_lineups
        WHERE fixture_id = ?
          AND version_type = ?
        """,
        (
            fixture_id,
            VERSION_TYPE,
        ),
    )

    return upsert_expected_team_lineups(
        connection=connection,
        lineups=lineups,
    )