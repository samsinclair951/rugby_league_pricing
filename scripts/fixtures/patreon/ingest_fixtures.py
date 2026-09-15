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

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))


from scripts.mapping.patreon.teams_mapping import (
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

TOURNAMENT_NAME = "Super League"
TOURNAMENT_COUNTRY = "England"
TOURNAMENT_TYPE = "league"


def normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Convert Patreon spreadsheet columns into our standard names.

    Add/edit aliases here if the Patreon workbook uses different headers.
    """
    frame = frame.copy()

    frame.columns = [
        str(column).strip().lower()
        .replace(" ", "_")
        .replace("-", "_")
        for column in frame.columns
    ]

    aliases = {
            "date": "match_date",
            "fixture_date": "match_date",
            "fixture_time": "kick_off",
    
            "home": "home_team",
            "home_side": "home_team",
    
            "away": "away_team",
            "away_side": "away_team",
    
            "home_points": "home_score",
            "away_points": "away_score",
            "home_ft_score": "home_score",
            "away_ft_score": "away_score",
    
            "ko": "kick_off",
            "kickoff": "kick_off",
    
            "stadium": "venue",
        }

    frame = frame.rename(
        columns={
            old: new
            for old, new in aliases.items()
            if old in frame.columns
        }
    )

    return frame


def load_matches(
    file_path: Path,
    season: int,
) -> list[dict[str, Any]]:
    """Load Patreon fixture rows from Excel."""

    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        frame = pd.read_csv(file_path)
    elif suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(file_path)
    else:
        raise ValueError(
            f"Unsupported Patreon file type: {suffix}"
        )

    frame = normalise_columns(frame)

    required = {
        "match_date",
        "home_team",
        "away_team",
    }

    missing = required - set(frame.columns)

    if missing:
        raise ValueError(
            f"Patreon file is missing required columns: "
            f"{sorted(missing)}. "
            f"Found: {frame.columns.tolist()}"
        )

    frame["match_date"] = pd.to_datetime(
        frame["match_date"],
        format="%Y-%m-%d",
        errors="raise",
    ).dt.strftime("%Y-%m-%d")

    frame["season"] = season

    if "kick_off" not in frame:
        frame["kick_off"] = None

    if "referee" not in frame:
        frame["referee"] = None

    if "venue" not in frame:
        frame["venue"] = None

    records: list[dict[str, Any]] = []

    for index, row in frame.iterrows():
        records.append(
            {
                "season": season,
                "match_date": row["match_date"],
                "kick_off": row["kick_off"],
                "home_team": str(row["home_team"]).strip(),
                "away_team": str(row["away_team"]).strip(),
                "referee": row["referee"],
                "venue": row["venue"],
                "source_name": SOURCE_NAME,
                "source_match_id": row["fixture_id"],
            }
        )

    return records


def reconcile_fixture_date(
    connection: sqlite3.Connection,
    match: dict[str, Any],
) -> None:
    """
    Remove an existing fixture for the same matchup if its date has changed.

    fixture_id contains the match date, so a corrected date otherwise creates
    a second fixture rather than updating the existing one.
    """

    existing = connection.execute(
        """
        SELECT fixture_id, match_date
        FROM fixtures
        WHERE season = ?
          AND home_team_id = ?
          AND away_team_id = ?
        """,
        (
            match["season"],
            match["home_team_id"],
            match["away_team_id"],
        ),
    ).fetchall()

    new_fixture_id = build_fixture_id(
        match_date=match["match_date"],
        home_team_id=match["home_team_id"],
        away_team_id=match["away_team_id"],
    )

    for fixture_id, existing_match_date in existing:
        if fixture_id == new_fixture_id:
            continue

        LOGGER.warning(
            "Fixture date changed: %s vs %s | %s -> %s",
            match["home_team_id"],
            match["away_team_id"],
            existing_match_date,
            match["match_date"],
        )

        connection.execute(
            """
            DELETE FROM fixtures
            WHERE fixture_id = ?
            """,
            (fixture_id,),
        )


def get_or_create_tournament(
    connection: sqlite3.Connection,
) -> int:
    """Return canonical Super League tournament ID."""

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
        return int(row[0])

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

    return int(cursor.lastrowid)


def prepare_fixtures(
    matches: list[dict[str, Any]],
    tournament_id: int,
) -> pd.DataFrame:
    """Prepare canonical fixture rows."""

    records = [
        {
            "fixture_id": build_fixture_id(
                match_date=match["match_date"],
                home_team_id=match["home_team_id"],
                away_team_id=match["away_team_id"],
            ),
            "season": match["season"],
            "tournament_id": tournament_id,
            "competition_stage_id": None,
            "match_date": match["match_date"],
            "kick_off": match["kick_off"],
            "home_team_id": match["home_team_id"],
            "away_team_id": match["away_team_id"],
            "referee": match["referee"],
            "venue": match["venue"],
            "source_name": SOURCE_NAME,
            "source_match_id": match["source_match_id"],
        }
        for match in matches
    ]

    return pd.DataFrame.from_records(records)


def upsert_fixtures(
    connection: sqlite3.Connection,
    fixtures: pd.DataFrame,
) -> int:
    """Insert/update fixture rows."""

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
        conflict_columns=["fixture_id"],
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


def ingest_file(
    connection: sqlite3.Connection,
    file_path: Path,
    season: int,
) -> int:

    matches = load_matches(
        file_path=file_path,
        season=season,
    )

    LOGGER.info(
        "Loaded %s Patreon fixture rows for %s",
        len(matches),
        season,
    )

    matches = apply_team_ids(
        connection=connection,
        matches=matches,
    )

    # for match in matches:
    #     reconcile_fixture_date(
    #         connection=connection,
    #         match=match,
    #     )
    
    # Fixture date reconciliation is handled separately.
    # Bulk ingestion must not match fixtures solely by home/away teams.

    tournament_id = get_or_create_tournament(
        connection
    )

    fixtures = prepare_fixtures(
        matches=matches,
        tournament_id=tournament_id,
    )

    return upsert_fixtures(
        connection=connection,
        fixtures=fixtures,
    )


def parse_arguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="Ingest Patreon Super League fixtures."
    )

    parser.add_argument(
        "--file",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--season",
        type=int,
        required=True,
    )

    return parser.parse_args()


def main() -> None:

    args = parse_arguments()

    with get_connection() as connection:

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        try:
            count = ingest_file(
                connection=connection,
                file_path=args.file,
                season=args.season,
            )

            connection.commit()

        except Exception:
            connection.rollback()
            raise

    LOGGER.info(
        "Inserted or updated %s Patreon fixtures.",
        count,
    )


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    main()