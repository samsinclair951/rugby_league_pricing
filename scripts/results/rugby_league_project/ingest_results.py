
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


from rugby_league_project.scraper import scrape_season_matches
from rugby_league_project.teams_mapping import (
    SOURCE_NAME,
    apply_team_ids,
    filter_super_league_matches,
)

from rugby_league_pricing.database.connection import (
    DEFAULT_DATABASE_PATH,
    get_connection,
)

LOGGER = logging.getLogger(__name__)


def filter_completed_results(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Keep only matches with both a home and away score.
    """
    return [
        match
        for match in matches
        if (
            match["home_score"] is not None
            and match["away_score"] is not None
        )
    ]


def prepare_results(
    mapped_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Select only the fields stored in the results table.
    """
    return [
        {
            "season": match["season"],
            "match_date": match["match_date"],
            "kick_off": match["kick_off"],
            "home_team_id": match["home_team_id"],
            "home_score": match["home_score"],
            "away_team_id": match["away_team_id"],
            "away_score": match["away_score"],
            "referee": match["referee"],
            "venue": match["venue"],
            "attendance": match["attendance"],
            "source_name": match["source_name"],
            "source_match_id": match["source_match_id"],
        }
        for match in mapped_matches
    ]


def upsert_results(
    connection: sqlite3.Connection,
    results: list[dict[str, Any]],
) -> int:
    if not results:
        return 0

    sql = """
        INSERT INTO results (
            season,
            match_date,
            kick_off,
            home_team_id,
            home_score,
            away_team_id,
            away_score,
            referee,
            venue,
            attendance,
            source_name,
            source_match_id
        )
        VALUES (
            :season,
            :match_date,
            :kick_off,
            :home_team_id,
            :home_score,
            :away_team_id,
            :away_score,
            :referee,
            :venue,
            :attendance,
            :source_name,
            :source_match_id
        )
        ON CONFLICT (
            source_name,
            season,
            match_date,
            home_team_id,
            away_team_id
        )
        DO UPDATE SET
            kick_off = excluded.kick_off,
            home_score = excluded.home_score,
            away_score = excluded.away_score,
            referee = excluded.referee,
            venue = excluded.venue,
            attendance = excluded.attendance,
            source_match_id = excluded.source_match_id,
            updated_at = CURRENT_TIMESTAMP
    """

    connection.executemany(
        sql,
        results,
    )

    return len(results)


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

    completed_matches = filter_completed_results(
        matches=league_matches,
    )

    LOGGER.info(
        "Season %s: found %s completed league results",
        season,
        len(completed_matches),
    )

    mapped_matches = apply_team_ids(
        connection=connection,
        matches=completed_matches,
        create_missing=False,
    )

    results = prepare_results(
        mapped_matches=mapped_matches,
    )

    result_count = upsert_results(
        connection=connection,
        results=results,
    )

    LOGGER.info(
        "Season %s: inserted or updated %s results",
        season,
        result_count,
    )

    return result_count


def validate_database(
    connection: sqlite3.Connection,
) -> None:
    required_tables = {
        "results",
        "teams",
        "team_source_mappings",
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
            "Ingest completed Super League results "
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
        "Finished. Inserted or updated %s results "
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