"""Build and rebuild base player-rating rows from Patreon player files."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from .upsert import upsert_player_ratings

PROJECT_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").exists()
)

PATREON_PLAYER_DIR = PROJECT_ROOT / "data" / "raw" / "patreon" / "players"

# Relative importance weighting per position id.
# Spine (1, 6, 7, 9) and props (8, 10) get the highest weights.
POSITION_IMPORTANCE: dict[int, float] = {
    1: 1.35,   # Fullback
    2: 1.10,   # Wing
    3: 1.05,   # Centre
    4: 1.00,   # Centre
    5: 1.00,   # Wing
    6: 1.25,   # Stand-off
    7: 1.20,   # Scrum-half
    8: 1.18,   # Prop
    9: 1.25,   # Hooker
    10: 1.18,  # Prop
    11: 1.05,  # Second-row
    12: 1.05,  # Second-row
    13: 1.05,  # Loose-forward
    14: 1.00,
    15: 1.00,
    16: 1.00,
    17: 1.00,
}


def load_player_data(directory: Path | None = None) -> pd.DataFrame:
    """Load and validate all Patreon player rows from CSV files."""
    player_dir = directory or PATREON_PLAYER_DIR

    if not player_dir.exists():
        raise FileNotFoundError(f"Player directory not found: {player_dir}")

    files = sorted(player_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No player CSV files found in {player_dir}")

    raw = pd.concat([pd.read_csv(path) for path in files], ignore_index=True)

    required = {
        "fixture_id",
        "player_id",
        "player_name",
        "position_id",
        "team_id",
        "opposition_id",
        "tries",
        "goals_made",
        "drop_goals",
        "tackles_made",
        "tackles_missed",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"Player data is missing expected columns: {sorted(missing)}")

    raw = raw.copy()
    raw["fixture_id"] = raw["fixture_id"].astype(str)
    raw["player_id"] = raw["player_id"].astype(str)
    raw["player_name"] = raw["player_name"].astype(str)
    raw["team_id"] = raw["team_id"].astype(str)
    raw["position_id"] = pd.to_numeric(raw["position_id"], errors="coerce")

    for col in ["tries", "goals_made", "drop_goals", "tackles_made", "tackles_missed"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce").fillna(0.0)

    return raw


def _compute_ratings(players: pd.DataFrame) -> pd.DataFrame:
    """Compute attack, defence, and overall ratings per fixture/player row."""
    players = players.copy()

    # Deduplicate so one player has one row per fixture/team.
    id_cols = ["fixture_id", "player_id", "player_name", "position_id", "team_id"]
    numeric_cols = (
        players.select_dtypes(include=np.number)
        .columns.difference(id_cols)
        .tolist()
    )
    players = players.groupby(["fixture_id", "player_id"], as_index=False).agg(
        {
            "player_name": "first",
            "position_id": "first",
            "team_id": "first",
            **{c: "sum" for c in numeric_cols},
        }
    )

    players["player_points"] = (
        4 * players["tries"]
        + 2 * players["goals_made"]
        + players["drop_goals"]
    )
    players["player_value"] = (
        players["player_points"]
        + 0.5 * players["tries"]
        + 0.25 * players["goals_made"]
        + 0.15 * players["tackles_made"]
        - 0.25 * players["tackles_missed"]
    )

    team_totals = (
        players.groupby(["fixture_id", "team_id"], as_index=False)["player_points"]
        .sum()
        .rename(columns={"player_points": "team_points"})
    )
    players = players.merge(team_totals, on=["fixture_id", "team_id"], how="left")

    players["team_share"] = np.where(
        players["team_points"].replace(0, np.nan).notna(),
        players["player_value"] / players["team_points"],
        0.0,
    )
    players["position_factor"] = (
        players["position_id"].map(POSITION_IMPORTANCE).fillna(1.0)
    )

    players["attack_rating"] = 10.0 * players["team_share"] * players["position_factor"]
    players["defence_rating"] = (
        (players["tackles_made"] - 0.5 * players["tackles_missed"])
        * 0.12
        * players["position_factor"]
    )
    players["overall_rating"] = players["attack_rating"] + players["defence_rating"]

    appearance_counts = (
        players.groupby("player_id")["fixture_id"].transform("count")
    )
    players["reliability"] = np.clip(np.sqrt(appearance_counts / 20.0), 0.0, 1.0)

    return players


def build_player_ratings(
    connection: sqlite3.Connection,
    directory: Path | None = None,
) -> pd.DataFrame:
    """Build a database-ready player-ratings frame.

    Loads Patreon player files, computes per-fixture ratings, and joins
    to the fixtures table for the season field.
    """
    raw = load_player_data(directory=directory)
    players = _compute_ratings(raw)

    fixture_meta = pd.read_sql_query(
        """
        SELECT
            fixture_id,
            season
        FROM fixtures
        """,
        connection,
    )
    fixture_meta["fixture_id"] = fixture_meta["fixture_id"].astype(str)

    players = players.merge(
        fixture_meta,
        on="fixture_id",
        how="left",
        validate="many_to_one",
    )

    if players["season"].isna().any():
        fallback = pd.to_numeric(
            players["fixture_id"].str[:4],
            errors="coerce",
        ).fillna(0)
        players["season"] = players["season"].fillna(fallback)

    players["season"] = pd.to_numeric(players["season"], errors="coerce").fillna(0).astype(int)
    players["position_id"] = pd.to_numeric(players["position_id"], errors="coerce")

    return players[
        [
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
    ].copy()


def rebuild_player_ratings(connection: sqlite3.Connection) -> int:
    """Build and persist player ratings to the database."""
    ratings = build_player_ratings(connection=connection)

    return upsert_player_ratings(
        connection=connection,
        player_ratings=ratings,
    )
