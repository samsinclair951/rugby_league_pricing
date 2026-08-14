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

from rugby_league_project.scraper import scrape_season_matches
from rugby_league_project.teams_mapping import (
    SOURCE_NAME,
    apply_team_ids,
    filter_super_league_matches,
)

from rugby_league_pricing.database.connection import (
    get_connection,
)
from rugby_league_pricing.utils.fixtures import build_fixture_id
from rugby_league_pricing.utils.sql import upsert_dataframe

LOGGER = logging.getLogger(__name__)

TOURNAMENT_NAME = "Super League"
TOURNAMENT_COUNTRY = "England"
TOURNAMENT_TYPE = "league"
SOURCE_TOURNAMENT_NAME = "Super League"


def get_or_create_tournament(
    connection: sqlite3.Connection,
) -> int:
    """
    Return the canonical Super League tournament ID.

    Creates the tournament if it does not already exist.
    """
    row = connection.execute(
        """
        SELECT tournament_id
        FROM tournaments
        WHERE tournament_name = ?
          AND country = ?
        """,
        (
            TOURNAMENT_NAME,
            TOURNAMENT_COUNTRY,
        ),
    ).fetchone()

    if row is not None:
        tournament_id = int(row[0])

        connection.execute(
            """
            UPDATE tournaments
            SET competition_type = ?,
                active = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE tournament_id = ?
            """,
            (
                TOURNAMENT_TYPE,
                tournament_id,
            ),
        )

        return tournament_id

    cursor = connection.execute(
        """
        INSERT INTO tournaments (
            tournament_name,
            country,
            competition_type,
            active
        )
        VALUES (?, ?, ?, 1)
        """,
        (
            TOURNAMENT_NAME,
            TOURNAMENT_COUNTRY,
            TOURNAMENT_TYPE,
        ),
    )

    tournament_id = int(cursor.lastrowid)

    LOGGER.info(
        "Created tournament: %s (%s) -> tournament_id %s",
        TOURNAMENT_NAME,
        TOURNAMENT_COUNTRY,
        tournament_id,
    )

    return tournament_id


def upsert_tournament_source_mapping(
    connection: sqlite3.Connection,
    tournament_id: int,
) -> None:
    """Ensure the Rugby League Project tournament mapping exists."""
    connection.execute(
        """
        INSERT INTO tournament_source_mappings (
            tournament_id,
            source_name,
            source_tournament_name
        )
        VALUES (?, ?, ?)

        ON CONFLICT (
            source_name,
            source_tournament_name
        )
        DO UPDATE SET
            tournament_id = excluded.tournament_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            tournament_id,
            SOURCE_NAME,
            SOURCE_TOURNAMENT_NAME,
        ),
    )


def get_or_create_competition_stage(
    connection: sqlite3.Connection,
    tournament_id: int,
    stage_name: str | None,
) -> int | None:
    """
    Return the canonical stage ID for one tournament.

    Stage is nullable because the scraper may not yet identify every
    historical competition stage.
    """
    if stage_name is None:
        return None

    cleaned_stage_name = stage_name.strip()

    if not cleaned_stage_name:
        return None

    row = connection.execute(
        """
        SELECT competition_stage_id
        FROM competition_stages
        WHERE tournament_id = ?
          AND stage_name = ?
        """,
        (
            tournament_id,
            cleaned_stage_name,
        ),
    ).fetchone()

    if row is not None:
        return int(row[0])

    cursor = connection.execute(
        """
        INSERT INTO competition_stages (
            tournament_id,
            stage_name
        )
        VALUES (?, ?)
        """,
        (
            tournament_id,
            cleaned_stage_name,
        ),
    )

    competition_stage_id = int(
        cursor.lastrowid
    )

    LOGGER.info(
        "Created competition stage: %s / %s -> competition_stage_id %s",
        TOURNAMENT_NAME,
        cleaned_stage_name,
        competition_stage_id,
    )

    return competition_stage_id


def add_competition_metadata(
    connection: sqlite3.Connection,
    mapped_matches: list[dict[str, Any]],
    tournament_id: int,
) -> list[dict[str, Any]]:
    """
    Attach tournament/stage IDs to mapped fixture records.

    The fixture scraper can optionally provide:
        competition_stage_name

    Until the scraper identifies historical stages, stage remains NULL rather
    than incorrectly labelling playoff matches as regular season.
    """
    stage_ids: dict[str, int] = {}

    for match in mapped_matches:
        match["tournament_id"] = tournament_id

        stage_name_raw = match.get(
            "competition_stage_name"
        )

        stage_name = (
            str(stage_name_raw).strip()
            if stage_name_raw
            else None
        )

        if stage_name is None:
            match["competition_stage_id"] = None
            continue

        if stage_name not in stage_ids:
            stage_id = get_or_create_competition_stage(
                connection=connection,
                tournament_id=tournament_id,
                stage_name=stage_name,
            )

            if stage_id is None:
                match["competition_stage_id"] = None
                continue

            stage_ids[stage_name] = stage_id

        match["competition_stage_id"] = (
            stage_ids[stage_name]
        )

    return mapped_matches


def update_team_tournaments(
    connection: sqlite3.Connection,
    mapped_matches: list[dict[str, Any]],
    tournament_id: int,
) -> None:
    """
    Set each participating team's current recognised tournament.

    This represents current/most recently observed league membership rather
    than a full historical membership record.
    """
    team_ids = {
        int(match["home_team_id"])
        for match in mapped_matches
    }

    team_ids.update(
        int(match["away_team_id"])
        for match in mapped_matches
    )

    connection.executemany(
        """
        UPDATE teams
        SET current_tournament_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE team_id = ?
        """,
        [
            (
                tournament_id,
                team_id,
            )
            for team_id in sorted(team_ids)
        ],
    )


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
            "tournament_id": match["tournament_id"],
            "competition_stage_id": match.get(
                "competition_stage_id"
            ),
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

    return pd.DataFrame.from_records(
        records
    )


def upsert_fixtures(
    connection: sqlite3.Connection,
    fixtures: pd.DataFrame,
) -> int:
    """Insert or update fixtures in SQLite."""
    if fixtures.empty:
        return 0

    columns = [
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
    ]

    return upsert_dataframe(
        connection=connection,
        dataframe=fixtures,
        table_name="fixtures",
        columns=columns,
        conflict_columns=[
            "fixture_id"
        ],
        update_columns=[
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
        update_timestamp=True,
    )


def ingest_season(
    connection: sqlite3.Connection,
    season: int,
) -> int:
    """
    Scrape and store every Super League fixture for one season.

    Both completed matches and future scheduled matches are included.
    """
    tournament_id = get_or_create_tournament(
        connection=connection,
    )

    upsert_tournament_source_mapping(
        connection=connection,
        tournament_id=tournament_id,
    )

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

    mapped_matches = add_competition_metadata(
        connection=connection,
        mapped_matches=mapped_matches,
        tournament_id=tournament_id,
    )

    update_team_tournaments(
        connection=connection,
        mapped_matches=mapped_matches,
        tournament_id=tournament_id,
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
        "fixtures",
        "teams",
        "team_source_mappings",
        "tournaments",
        "tournament_source_mappings",
        "competition_stages",
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
        help="First season to ingest, for example 2025.",
    )

    parser.add_argument(
        "--end-season",
        type=int,
        required=True,
        help="Final season to ingest, for example 2026.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    if args.start_season > args.end_season:
        raise ValueError(
            "--start-season cannot be later than --end-season"
        )

    total_ingested = 0

    with get_connection() as connection:
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        validate_database(
            connection=connection,
        )

        for season in range(
            args.start_season,
            args.end_season + 1,
        ):
            try:
                fixture_count = ingest_season(
                    connection=connection,
                    season=season,
                )

                connection.commit()

                total_ingested += fixture_count

                LOGGER.info(
                    "Season %s committed successfully.",
                    season,
                )

            except Exception:
                connection.rollback()

                LOGGER.exception(
                    "Season %s failed. "
                    "Rolled back this season only.",
                    season,
                )

                raise

    LOGGER.info(
        "Finished. Inserted or updated %s fixtures from %s.",
        total_ingested,
        SOURCE_NAME,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    main()