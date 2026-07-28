from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").exists()
)

SCRIPTS_ROOT = PROJECT_ROOT / "scripts"

if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from rugby_league_pricing.utils.fixtures import build_fixture_id
from rugby_league_pricing.utils.sql import upsert_dataframe

LOGGER = logging.getLogger(__name__)


def prepare_fixtures(
    mapped_matches: list[dict[str, Any]],
) -> pd.DataFrame:
    """
    Select only the fields stored in the fixtures table.

    Fixtures contains every scheduled league match, including matches
    which have already been completed. Scores are deliberately omitted.
    """
    records = [
        {
            "fixture_id": build_fixture_id(
                match_date=match["match_date"],
                home_team_id=match["home_team_id"],
                away_team_id=match["away_team_id"],
            ),
            "season": match["season"],
            "match_date": match["match_date"],
            "kick_off": match["kick_off"],
            "home_team_id": match["home_team_id"],
            "away_team_id": match["away_team_id"],
            "referee": match["referee"],
            "venue": match["venue"],
            "source_name": match["source_name"],
            "source_match_id": match["source_match_id"],
        }
        for match in mapped_matches
    ]

    return pd.DataFrame.from_records(records)


def upsert_fixtures(
    connection: sqlite3.Connection,
    fixtures: pd.DataFrame,
) -> int:
    """Insert or update fixtures in SQLite."""
    columns = [
        "fixture_id",
        "season",
        "match_date",
        "kick_off",
        "home_team_id",
        "away_team_id",
        "referee",
        "venue",
        "source_name",
        "source_match_id",
    ]

    return upsert_dataframe(
        connection=connection,
        dataframe=fixtures,
        table_name="fixtures",
        columns=columns,
        conflict_columns=["fixture_id"],
        update_timestamp=True,
    )
