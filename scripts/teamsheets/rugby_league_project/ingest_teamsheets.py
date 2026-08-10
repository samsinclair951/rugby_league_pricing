from __future__ import annotations

import argparse
import hashlib
import logging
import sqlite3
import sys
from collections import Counter
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

from scripts.rugby_league_project.teams_mapping import (
    SOURCE_NAME,
    apply_team_ids,
)

from src.rugby_league_pricing.database.connection import get_connection
from scripts.teamsheets.rugby_league_project.scraper import (
    scrape_match_teamsheet,
    scrape_season_match_references,
)
from src.rugby_league_pricing.utils.fixtures import build_fixture_id
from src.rugby_league_pricing.utils.sql import upsert_dataframe

LOGGER = logging.getLogger(__name__)


def build_player_id(
    source_player_id: str | None,
    player_name: str,
) -> str:
    """
    Build a stable player identifier.

    Prefer Rugby League Project's own player identifier. Historical pages without
    a player link fall back to a deterministic hash of the normalised name.
    """
    if source_player_id:
        return f"rlp_{source_player_id}"

    normalised_name = " ".join(player_name.lower().split())
    digest = hashlib.sha1(
        normalised_name.encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:16]

    return f"rlp_name:{digest}"


def resolve_fixture_id(
    connection: sqlite3.Connection,
    season: int,
    home_team_id: int,
    away_team_id: int,
    source_match_id: str,
    match_date_text: str,
) -> str:
    """
    Resolve a scraped teamsheet to an existing fixture.

    Prefer source_match_id when available, but fall back to the fixture date
    because older fixture ingestion used a different RLP source-match-id format.
    """

    row = connection.execute(
        """
        SELECT fixture_id
        FROM fixtures
        WHERE season = ?
          AND source_name = ?
          AND source_match_id = ?
        """,
        (
            season,
            SOURCE_NAME,
            source_match_id,
        ),
    ).fetchone()

    if row is not None:
        return str(row[0])

    scraped_date = pd.to_datetime(
        f"{match_date_text} {season}",
        errors="coerce",
        dayfirst=False,
    )

    if pd.isna(scraped_date):
        raise RuntimeError(
            "Could not parse teamsheet match date: "
            f"{match_date_text!r}"
        )

    rows = connection.execute(
        """
        SELECT fixture_id
        FROM fixtures
        WHERE season = ?
          AND home_team_id = ?
          AND away_team_id = ?
          AND DATE(match_date) = ?
        """,
        (
            season,
            home_team_id,
            away_team_id,
            scraped_date.date().isoformat(),
        ),
    ).fetchall()

    if len(rows) == 1:
        return str(rows[0][0])

    if not rows:
        raise RuntimeError(
            "Could not match teamsheet to fixture: "
            f"season={season}, "
            f"date={scraped_date.date()}, "
            f"home_team_id={home_team_id}, "
            f"away_team_id={away_team_id}"
        )

    raise RuntimeError(
        "Multiple fixtures matched teamsheet: "
        f"season={season}, "
        f"date={scraped_date.date()}, "
        f"home_team_id={home_team_id}, "
        f"away_team_id={away_team_id}"
    )


def prepare_match_records(
    connection: sqlite3.Connection,
    season: int,
    home_team: str,
    away_team: str,
    source_match_id: str,
    summary_url: str,
    match_date_text: str,
    scraped_players: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Convert one scraped match teamsheet into normalised player and teamsheet rows.
    """
    mapped_match = apply_team_ids(
        connection=connection,
        matches=[
            {
                "season": season,
                "home_team_name": home_team,
                "away_team_name": away_team,
                "source_name": SOURCE_NAME,
                "source_match_id": source_match_id,
            }
        ],
        create_missing=True,
    )[0]

    home_team_id = int(mapped_match["home_team_id"])
    away_team_id = int(mapped_match["away_team_id"])

    fixture_id = resolve_fixture_id(
        connection=connection,
        season=season,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        source_match_id=source_match_id,
        match_date_text=match_date_text,
    )

    player_rows: list[dict[str, Any]] = []
    teamsheet_rows: list[dict[str, Any]] = []

    for player in scraped_players:
        side = str(player["side"])
        team_id = home_team_id if side == "home" else away_team_id
        player_name = str(player["player_name"])

        player_id = build_player_id(
            source_player_id=(
                str(player["source_player_id"])
                if player.get("source_player_id")
                else None
            ),
            player_name=player_name,
        )

        player_rows.append(
            {
                "player_id": player_id,
                "player_name": player_name,
                "season": season,
                "team_id": team_id,
                "primary_position": player.get("position"),
                "active": 1,
                "source_name": SOURCE_NAME,
                "source_player_id": player.get("source_player_id"),
            }
        )

        teamsheet_rows.append(
            {
                "fixture_id": fixture_id,
                "season": season,
                "team_id": team_id,
                "player_id": player_id,
                "side": side,
                "position": player.get("position"),
                "lineup_order": int(player["lineup_order"]),
                "is_starting": int(bool(player["is_starting"])),
                "source_name": SOURCE_NAME,
                "source_match_id": source_match_id,
                "source_url": summary_url,
            }
        )

    return player_rows, teamsheet_rows


def prepare_players(
    player_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    """
    Collapse appearance-level player records into one row per player/team/season.

    primary_position is inferred as the player's most common teamsheet position
    for that team in that season. Only players who actually appear are stored.
    """
    if not player_rows:
        return pd.DataFrame()

    raw = pd.DataFrame.from_records(player_rows)

    grouped_records: list[dict[str, Any]] = []

    for (player_id, season, team_id), group in raw.groupby(
        ["player_id", "season", "team_id"],
        sort=False,
    ):
        positions = [
            str(value)
            for value in group["primary_position"].dropna()
            if str(value).strip()
        ]

        primary_position = (
            Counter(positions).most_common(1)[0][0]
            if positions
            else None
        )

        first = group.iloc[0]

        grouped_records.append(
            {
                "player_id": player_id,
                "player_name": first["player_name"],
                "season": int(season),
                "team_id": int(team_id),
                "primary_position": primary_position,
                "active": 1,
                "source_name": first["source_name"],
                "source_player_id": first["source_player_id"],
            }
        )

    return pd.DataFrame.from_records(grouped_records)


def prepare_teamsheets(
    teamsheet_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    if not teamsheet_rows:
        return pd.DataFrame()

    return pd.DataFrame.from_records(teamsheet_rows)


def upsert_players(
    connection: sqlite3.Connection,
    players: pd.DataFrame,
) -> int:
    """Insert or update player/team/season records in SQLite."""
    if players.empty:
        return 0

    columns = [
        "player_id",
        "player_name",
        "season",
        "team_id",
        "primary_position",
        "active",
        "source_name",
        "source_player_id",
    ]

    return upsert_dataframe(
        connection=connection,
        dataframe=players,
        table_name="players",
        columns=columns,
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


def upsert_teamsheets(
    connection: sqlite3.Connection,
    teamsheets: pd.DataFrame,
) -> int:
    """Insert or update fixture teamsheets in SQLite."""
    if teamsheets.empty:
        return 0

    columns = [
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
    ]

    return upsert_dataframe(
        connection=connection,
        dataframe=teamsheets,
        table_name="teamsheets",
        columns=columns,
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


def ingest_season(
    connection: sqlite3.Connection,
    season: int,
) -> tuple[int, int]:
    """
    Scrape and store every available Super League teamsheet for one season.

    Only players who actually appear in a matchday teamsheet are written to the
    players table.
    """
    match_references = scrape_season_match_references(
        season=season,
    )

    LOGGER.info(
        "Season %s: found %s match detail pages",
        season,
        len(match_references),
    )

    all_player_rows: list[dict[str, Any]] = []
    all_teamsheet_rows: list[dict[str, Any]] = []

    for match in match_references:
        try:
            scraped_players = scrape_match_teamsheet(
                summary_url=match.summary_url,
            )
        except RuntimeError as exc:
            LOGGER.warning(
                "Season %s: skipping %s vs %s: %s",
                season,
                match.home_team,
                match.away_team,
                exc,
            )
            continue

        player_rows, teamsheet_rows = prepare_match_records(
            connection=connection,
            season=season,
            home_team=match.home_team,
            away_team=match.away_team,
            source_match_id=match.source_match_id,
            summary_url=match.summary_url,
            match_date_text=match.match_date_text,
            scraped_players=scraped_players,
        )

        all_player_rows.extend(player_rows)
        all_teamsheet_rows.extend(teamsheet_rows)

        LOGGER.info(
            "Season %s: scraped %s vs %s (%s players)",
            season,
            match.home_team,
            match.away_team,
            len(scraped_players),
        )

    players = prepare_players(
        player_rows=all_player_rows,
    )

    teamsheets = prepare_teamsheets(
        teamsheet_rows=all_teamsheet_rows,
    )

    player_count = upsert_players(
        connection=connection,
        players=players,
    )

    teamsheet_count = upsert_teamsheets(
        connection=connection,
        teamsheets=teamsheets,
    )

    LOGGER.info(
        "Season %s: inserted or updated %s player-season-team rows",
        season,
        player_count,
    )

    LOGGER.info(
        "Season %s: inserted or updated %s teamsheet rows",
        season,
        teamsheet_count,
    )

    return player_count, teamsheet_count


def validate_database(
    connection: sqlite3.Connection,
) -> None:
    required_tables = {
        "fixtures",
        "players",
        "teams",
        "teamsheets",
        "team_source_mappings",
    }

    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        """
    ).fetchall()

    existing_tables = {str(row[0]) for row in rows}
    missing_tables = required_tables - existing_tables

    if missing_tables:
        raise RuntimeError(
            f"Database is missing required tables: {sorted(missing_tables)}"
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest Super League match teamsheets and playing players "
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
        raise ValueError("--start-season cannot be later than --end-season")

    total_players = 0
    total_teamsheet_rows = 0

    with get_connection() as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        validate_database(
            connection=connection,
        )

        try:
            for season in range(
                args.start_season,
                args.end_season + 1,
            ):
                player_count, teamsheet_count = ingest_season(
                    connection=connection,
                    season=season,
                )

                total_players += player_count
                total_teamsheet_rows += teamsheet_count

            connection.commit()

        except Exception:
            connection.rollback()
            raise

    LOGGER.info(
        "Finished. Inserted or updated %s player-season-team rows and "
        "%s teamsheet rows from %s.",
        total_players,
        total_teamsheet_rows,
        SOURCE_NAME,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    main()
