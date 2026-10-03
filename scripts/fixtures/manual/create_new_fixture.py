from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from scripts.fixtures.rugby_league_project.ingest_fixtures import (
    TOURNAMENT_NAME,
    build_fixture_id,
    get_or_create_tournament,
)
from scripts.fixtures.manual.update_fixture import get_team_id
from rugby_league_pricing.utils.sql import upsert_dataframe

import pandas as pd


LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATABASE_PATH = REPO_ROOT / "data" / "rugby_league_pricing.db"

SOURCE_NAME = "manual"


def create_new_fixture(
    *,
    fixture_date: str,
    home_team: str,
    away_team: str,
    kick_off: str,
    neutral_venue: bool = False,
) -> str:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        home_team_id = get_team_id(connection, home_team)
        away_team_id = get_team_id(connection, away_team)

        season = datetime.strptime(fixture_date, "%Y-%m-%d").year

        fixture_id = build_fixture_id(
            match_date=fixture_date,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
        )

        tournament_id = get_or_create_tournament(
            connection=connection,
            tournament_name=TOURNAMENT_NAME,
        )

        fixture = pd.DataFrame.from_records(
            [
                {
                    "fixture_id": fixture_id,
                    "season": season,
                    "tournament_id": tournament_id,
                    "competition_stage_id": None,
                    "match_date": fixture_date,
                    "kick_off": kick_off,
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "referee": None,
                    "venue": "Neutral" if neutral_venue else None,
                    "source_name": SOURCE_NAME,
                    "source_match_id": None,
                }
            ]
        )

        upsert_dataframe(
            connection=connection,
            dataframe=fixture,
            table_name="fixtures",
            columns=[
                "fixture_id",
                "season",
                "tournament_id",
                "competition_stage_id",
                "match_date",
                "kick_off",
                "home_team_id",
                "away_team_id",
                "referee",
                "venue",
                "source_name",
                "source_match_id",
            ],
            conflict_columns=["fixture_id"],
            update_columns=[
                "season",
                "tournament_id",
                "competition_stage_id",
                "match_date",
                "kick_off",
                "home_team_id",
                "away_team_id",
                "venue",
                "source_name",
            ],
            update_timestamp=True,
        )

        connection.commit()

        LOGGER.info(
            "Created fixture: %s vs %s on %s (%s) -> fixture_id %s",
            home_team,
            away_team,
            fixture_date,
            kick_off,
            fixture_id,
        )

        return fixture_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manually create (or upsert) a fixture."
    )

    parser.add_argument("--date", required=True, help="Fixture date, YYYY-MM-DD.")
    parser.add_argument("--home", required=True, help="Home team canonical name.")
    parser.add_argument("--away", required=True, help="Away team canonical name.")
    parser.add_argument("--time", required=True, help="Kick-off time, e.g. 19:45.")
    parser.add_argument(
        "--neutral-venue",
        action="store_true",
        default=False,
        help="Set if the fixture is played at a neutral venue.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    create_new_fixture(
        fixture_date=args.date,
        home_team=args.home,
        away_team=args.away,
        kick_off=args.time,
        neutral_venue=args.neutral_venue,
    )


if __name__ == "__main__":
    main()
