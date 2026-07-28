from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").exists()
)

SCRIPTS_ROOT = PROJECT_ROOT / "scripts"

if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from rugby_league_project.scraper import (
    scrape_season_matches,
)
from rugby_league_project.teams_mapping import (
    SOURCE_NAME,
    apply_team_ids,
    filter_super_league_matches,
)

from rugby_league_pricing.database.connection import (
    DEFAULT_DATABASE_PATH,
    get_connection,
)
from rugby_league_pricing.utils.fixtures import build_fixture_id

LOGGER = logging.getLogger(__name__)


def prepare_fixtures(
    mapped_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Select only the fields stored in the fixtures table.

    Fixtures contains every scheduled league match, including matches
    which have already been completed. Scores are deliberately omitted.
    """
    return [
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


def upsert_fixtures(
    connection: sqlite3.Connection,
    fixtures: list[dict[str, Any]],
) -> int:
    if not fixtures:
        return 0

    sql = """
        INSERT INTO fixtures (
            fixture_id,
            season,
            match_date,
            kick_off,
            home_team_id,
            away_team_id,
            referee,
            venue,
            source_name,
            source_match_id
        )
        VALUES (
            :fixture_id,
            :season,
            :match_date,
            :kick_off,
            :home_team_id,
            :away_team_id,
            :referee,
            :venue,
            :source_name,
            :source_match_id
        )
        ON CONFLICT (fixture_id)
        DO UPDATE SET
            season = excluded.season,
            match_date = excluded.match_date,
            kick_off = excluded.kick_off,
            home_team_id = excluded.home_team_id,
            away_team_id = excluded.away_team_id,
            referee = excluded.referee,
            venue = excluded.venue,
            source_name = excluded.source_name,
            source_match_id = excluded.source_match_id,
            updated_at = CURRENT_TIMESTAMP
    """

    connection.executemany(
        sql,
        fixtures,
    )

    return len(fixtures)


def ingest_season(
    connection: sqlite3.Connection,
    season: int,
) -> int:
    all_matches = scrape_season_matches(
        season=season,
    )

    LOGGER.info(
        "Season %s: scraped %s total matches",
        season,
        len(all_matches),
    )

    league_matches = filter_super_league_matches(
        matches=all_matches,
        season=season,
    )

    LOGGER.info(
        "Season %s: found %s league fixtures",
        season,
        len(league_matches),
    )

    mapped_matches = apply_team_ids(
        connection=connection,
        matches=league_matches,
        create_missing=True,
    )

    fixtures = prepare_fixtures(
        mapped_matches=mapped_matches,
    )

    fixture_count = upsert_fixtures(
        connection=connection,
        fixtures=fixtures,
    )

    LOGGER.info(
        "Season %s: inserted or updated %s fixtures",
        season,
        fixture_count,
    )

    return fixture_count


def validate_database(
    connection: sqlite3.Connection,
) -> None:
    required_tables = {
        "teams",
        "team_source_mappings",
        "fixtures",
    }

    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        """
    ).fetchall()

    existing_tables = {
        str(row[0])
        for row in rows
    }

    missing_tables = (
        required_tables
        - existing_tables
    )

    if missing_tables:
        raise RuntimeError(
            "Database is missing required tables: "
            f"{sorted(missing_tables)}"
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest all scheduled Super League fixtures "
            "from Rugby League Project into SQLite."
        )
    )

    parser.add_argument(
        "--start-season",
        type=int,
        required=True,
        help="First season to ingest, for example 2022.",
    )

    parser.add_argument(
        "--end-season",
        type=int,
        required=True,
        help="Final season to ingest, for example 2026.",
    )

    parser.add_argument(
        "--database-path",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=(
            "SQLite database path. "
            f"Default: {DEFAULT_DATABASE_PATH}"
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    if args.start_season > args.end_season:
        raise ValueError(
            "--start-season cannot be later "
            "than --end-season"
        )

    if not args.database_path.exists():
        raise FileNotFoundError(
            f"Database does not exist: "
            f"{args.database_path}"
        )

    LOGGER.info(
        "Using database: %s",
        args.database_path,
    )

    total_ingested = 0

    with get_connection(
        args.database_path,
    ) as connection:
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        validate_database(
            connection=connection,
        )

        try:
            for season in range(
                args.start_season,
                args.end_season + 1,
            ):
                total_ingested += ingest_season(
                    connection=connection,
                    season=season,
                )

            connection.commit()

        except Exception:
            connection.rollback()
            raise

    LOGGER.info(
        "Finished. Inserted or updated %s fixtures "
        "from %s.",
        total_ingested,
        SOURCE_NAME,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    main()