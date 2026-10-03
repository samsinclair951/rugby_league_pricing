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


def normalise_columns(
    frame: pd.DataFrame,
) -> pd.DataFrame:

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

    return frame.rename(
        columns={
            old: new
            for old, new in aliases.items()
            if old in frame.columns
        }
    )


def load_results(
    file_path: Path,
    season: int,
) -> list[dict[str, Any]]:

    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        frame = pd.read_csv(file_path)
    elif suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(file_path)
    else:
        raise ValueError(
            f"Unsupported Patreon file type: {suffix}"
        )

    frame = normalise_columns(
        frame
    )

    required = {
        "match_date",
        "home_team",
        "away_team",
        "home_score",
        "away_score",
    }

    missing = required - set(frame.columns)

    if missing:
        raise ValueError(
            f"Patreon file missing columns: "
            f"{sorted(missing)}. "
            f"Found: {frame.columns.tolist()}"
        )

    frame["match_date"] = pd.to_datetime(
        frame["match_date"],
        format="%Y-%m-%d",
        errors="raise",
    ).dt.strftime("%Y-%m-%d")

    # Only completed games.
    frame = frame[
        frame["home_score"].notna()
        & frame["away_score"].notna()
    ].copy()

    optional_columns = [
        "kick_off",
        "referee",
        "venue",
        "attendance",
    ]

    for column in optional_columns:
        if column not in frame:
            frame[column] = None

    matches = []

    for index, row in frame.iterrows():

        matches.append(
            {
                "season": season,
                "match_date": row["match_date"],
                "kick_off": row["kick_off"],
                "home_team": str(
                    row["home_team"]
                ).strip(),
                "away_team": str(
                    row["away_team"]
                ).strip(),
                "home_score": int(
                    row["home_score"]
                ),
                "away_score": int(
                    row["away_score"]
                ),
                "referee": row["referee"],
                "venue": row["venue"],
                "attendance": row["attendance"],
                "source_name": SOURCE_NAME,
                "source_match_id": row["fixture_id"],
            }
        )

    return matches


def prepare_results(
    matches: list[dict[str, Any]],
) -> pd.DataFrame:

    return pd.DataFrame.from_records(
        [
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
                "source_name": SOURCE_NAME,
                "source_match_id": match["source_match_id"],
            }
            for match in matches
        ]
    )


def upsert_results(
    connection: sqlite3.Connection,
    results: pd.DataFrame,
) -> int:

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
        conflict_columns=["fixture_id"],
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


def ingest_file(
    connection: sqlite3.Connection,
    file_path: Path,
    season: int,
) -> int:

    matches = load_results(
        file_path=file_path,
        season=season,
    )

    matches = apply_team_ids(
        connection=connection,
        matches=matches,
    )

    results = prepare_results(
        matches
    )

    return upsert_results(
        connection=connection,
        results=results,
    )


def parse_arguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="Ingest Patreon Super League results."
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
        "Inserted or updated %s Patreon results.",
        count,
    )


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    main()