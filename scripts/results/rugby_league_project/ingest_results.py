from __future__ import annotations

import argparse
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


from scripts.mapping.rugby_league_project.corrections import (
    apply_fixture_date_corrections,
)
from scripts.mapping.rugby_league_project.scraper import (
    get_competition_config,
    scrape_season_matches,
)
from scripts.mapping.rugby_league_project.teams_mapping import (
    SOURCE_NAME,
    apply_team_ids,
)

from rugby_league_pricing.database.connection import (
    get_connection,
)
from rugby_league_pricing.utils.fixtures import (
    build_fixture_id,
)
from rugby_league_pricing.utils.sql import (
    upsert_dataframe,
)


LOGGER = logging.getLogger(__name__)


def filter_completed_results(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only matches with both a home and away score."""

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
) -> pd.DataFrame:
    """Select only the fields stored in the results table."""

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

    return pd.DataFrame.from_records(
        records
    )


def upsert_results(
    connection: sqlite3.Connection,
    results: pd.DataFrame,
) -> int:
    """Insert or update completed results in SQLite."""

    if results.empty:
        return 0

    columns = [
        "fixture_id",
        "season",
        "match_date",
        "kick_off",
        "home_team_id",
        "home_score",
        "away_team_id",
        "away_score",
        "referee",
        "venue",
        "attendance",
        "source_name",
        "source_match_id",
    ]

    return upsert_dataframe(
        connection=connection,
        dataframe=results,
        table_name="results",
        columns=columns,
        conflict_columns=[
            "fixture_id"
        ],
        update_columns=[
            "kick_off",
            "home_score",
            "away_score",
            "referee",
            "venue",
            "attendance",
            "source_name",
            "source_match_id",
        ],
        update_timestamp=True,
    )


def ingest_season(
    connection: sqlite3.Connection,
    season: int,
    competition: str,
) -> int:
    config = get_competition_config(
        competition
    )

    tournament_name = (
        config["tournament_name"]
    )

    all_matches = scrape_season_matches(
        season=season,
        competition=competition,
    )

    LOGGER.info(
        "Season %s: scraped %s total %s matches",
        season,
        len(all_matches),
        tournament_name,
    )

    completed_matches = filter_completed_results(
        matches=all_matches,
    )

    LOGGER.info(
        "Season %s: found %s completed %s results",
        season,
        len(completed_matches),
        tournament_name,
    )

    if not completed_matches:
        return 0

    mapped_matches = apply_team_ids(
        connection=connection,
        matches=completed_matches,
        create_missing=True,
    )

    # Apply verified RLP date corrections BEFORE
    # fixture_id is constructed.
    mapped_matches = apply_fixture_date_corrections(
        matches=mapped_matches,
    )

    results = prepare_results(
        mapped_matches=mapped_matches,
    )

    result_count = upsert_results(
        connection=connection,
        results=results,
    )

    LOGGER.info(
        "Season %s: inserted or updated %s %s results",
        season,
        result_count,
        tournament_name,
    )

    return result_count


def validate_database(
    connection: sqlite3.Connection,
) -> None:
    required_tables = {
        "results",
        "fixtures",
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
            "Ingest completed rugby league results "
            "from Rugby League Project into SQLite."
        )
    )

    parser.add_argument(
        "--start-season",
        type=int,
        required=True,
        help="First season to ingest, for example 2024.",
    )

    parser.add_argument(
        "--end-season",
        type=int,
        required=True,
        help="Final season to ingest, for example 2026.",
    )

    parser.add_argument(
        "--competition",
        choices=[
            "super_league",
            "nrl",
        ],
        default="super_league",
        help=(
            "Competition to ingest. "
            "Defaults to super_league."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    if args.start_season > args.end_season:
        raise ValueError(
            "--start-season cannot be later than --end-season"
        )

    config = get_competition_config(
        args.competition
    )

    tournament_name = (
        config["tournament_name"]
    )

    total_ingested = 0

    with get_connection() as connection:
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
                    competition=args.competition,
                )

            connection.commit()

        except Exception:
            connection.rollback()
            raise

    LOGGER.info(
        "Finished. Inserted or updated %s %s results from %s.",
        total_ingested,
        tournament_name,
        SOURCE_NAME,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    main()
