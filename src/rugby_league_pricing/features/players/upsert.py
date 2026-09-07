"""Upsert helpers for player-rating rows."""

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
    "season",
    "attack_rating",
    "defence_rating",
    "overall_rating",
    "reliability",
]


def upsert_player_ratings(
    connection: sqlite3.Connection,
    player_ratings: pd.DataFrame,
) -> int:
    """Insert or update player-rating rows."""
    if player_ratings.empty:
        return 0

    missing_columns = set(UPSERT_COLUMNS).difference(player_ratings.columns)

    if missing_columns:
        raise ValueError(
            "Player ratings are missing required columns: "
            f"{sorted(missing_columns)}"
        )

    duplicate_rows = player_ratings.duplicated(
        subset=["fixture_id", "team_id", "player_id"]
    )

    if duplicate_rows.any():
        duplicates = player_ratings.loc[
            duplicate_rows,
            ["fixture_id", "team_id", "player_id"],
        ].to_dict(orient="records")

        raise ValueError(
            "Player ratings contain duplicate fixture/team/player rows: "
            f"{duplicates}"
        )

    return upsert_dataframe(
        connection=connection,
        dataframe=player_ratings,
        table_name="player_ratings",
        columns=UPSERT_COLUMNS,
        conflict_columns=["fixture_id", "team_id", "player_id"],
        update_timestamp=True,
    )
