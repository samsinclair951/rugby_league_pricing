from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.utils.sql import upsert_dataframe

PROJECT_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").exists()
)

PLAYERS_PATH = PROJECT_ROOT / "data" / "players.parquet"
TEAMSHEETS_PATH = PROJECT_ROOT / "data" / "teamsheets.parquet"


def load_players(
    connection: sqlite3.Connection,
) -> int:
    players = pd.read_parquet(
        PLAYERS_PATH
    )

    return upsert_dataframe(
        connection=connection,
        dataframe=players,
        table_name="players",
        columns=[
            "player_id",
            "player_name",
            "season",
            "team_id",
            "primary_position",
            "active",
            "source_name",
            "source_player_id",
        ],
        conflict_columns=[
            "player_id",
            "season",
            "team_id",
        ],
        update_columns=[
            "player_name",
            "primary_position",
            "active",
            "source_name",
            "source_player_id",
        ],
        update_timestamp=True,
    )


def load_teamsheets(
    connection: sqlite3.Connection,
) -> int:
    teamsheets = pd.read_parquet(
        TEAMSHEETS_PATH
    )

    return upsert_dataframe(
        connection=connection,
        dataframe=teamsheets,
        table_name="teamsheets",
        columns=[
            "fixture_id",
            "season",
            "team_id",
            "player_id",
            "side",
            "position",
            "lineup_order",
            "is_starting",
            "source_name",
            "source_match_id",
            "source_url",
        ],
        conflict_columns=[
            "fixture_id",
            "team_id",
            "player_id",
        ],
        update_columns=[
            "season",
            "side",
            "position",
            "lineup_order",
            "is_starting",
            "source_name",
            "source_match_id",
            "source_url",
        ],
        update_timestamp=True,
    )


def main() -> None:
    if not PLAYERS_PATH.exists():
        raise FileNotFoundError(
            f"Missing players parquet: {PLAYERS_PATH}"
        )

    if not TEAMSHEETS_PATH.exists():
        raise FileNotFoundError(
            f"Missing teamsheets parquet: {TEAMSHEETS_PATH}"
        )

    with get_connection() as connection:
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        player_count = load_players(
            connection=connection,
        )

        teamsheet_count = load_teamsheets(
            connection=connection,
        )

        connection.commit()

    print(
        f"Loaded {player_count} player rows "
        f"and {teamsheet_count} teamsheet rows "
        "from parquet."
    )


if __name__ == "__main__":
    main()