from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

import pandas as pd

from src.rugby_league_pricing.database.connection import get_connection
from src.rugby_league_pricing.utils.sql import upsert_dataframe


LOGGER = logging.getLogger(__name__)

SOURCE_NAME = "patreon"

PROJECT_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").exists()
)

PLAYER_FILES = [
    PROJECT_ROOT / "data/raw/patreon/players/sl_player_data_19_25.csv",
    PROJECT_ROOT / "data/raw/patreon/players/2026_sl_player_data.csv",
]


def load_patreon_players() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for path in PLAYER_FILES:
        if not path.exists():
            LOGGER.warning("Player file does not exist: %s", path)
            continue

        LOGGER.info("Loading Patreon player data from %s", path)

        frame = pd.read_csv(path)

        frame["source_lineup_order"] = (
            frame.groupby(
                ["fixture_id", "team_id"],
                sort=False,
            ).cumcount()
            + 1
        )

        frames.append(
            frame[
                [
                    "fixture_id",
                    "fixture_url",
                    "player_id",
                    "player_name",
                    "position_id",
                    "team_id",
                    "source_lineup_order",
                ]
            ].copy()
        )

    if not frames:
        raise RuntimeError("No Patreon player files were found.")


    players = pd.concat(frames, ignore_index=True)

    players = players.rename(
        columns={
            "fixture_id": "source_fixture_id",
            "player_id": "source_player_id",
            "team_id": "source_team_name",
        }
    )

    players["source_fixture_id"] = (
        players["source_fixture_id"].astype(str)
    )
    players["source_player_id"] = (
        players["source_player_id"].astype(str)
    )
    players["source_team_name"] = (
        players["source_team_name"].astype(str)
    )

    return players


def attach_fixture_mappings(
    connection: sqlite3.Connection,
    players: pd.DataFrame,
) -> pd.DataFrame:
    mappings = pd.read_sql_query(
        """
        SELECT
            CAST(fsm.source_fixture_id AS TEXT) AS source_fixture_id,
            CAST(f.fixture_id AS TEXT) AS fixture_id,
            f.season
        FROM fixture_source_mappings fsm
        JOIN fixtures f
            ON f.fixture_id = fsm.fixture_id
        WHERE fsm.source_name = 'patreon'
        """,
        connection,
    )

    frame = players.merge(
        mappings,
        on="source_fixture_id",
        how="left",
        validate="many_to_one",
    )

    missing = frame["fixture_id"].isna()

    if missing.any():
        examples = (
            frame.loc[missing, "source_fixture_id"]
            .drop_duplicates()
            .head(10)
            .tolist()
        )

        raise ValueError(
            f"{missing.sum()} Patreon player rows have no canonical fixture "
            f"mapping. Examples: {examples}"
        )

    return frame


def attach_team_mappings(
    connection: sqlite3.Connection,
    players: pd.DataFrame,
) -> pd.DataFrame:
    mappings = pd.read_sql_query(
        """
        SELECT
            team_id,
            source_team_name,
            valid_from_season,
            valid_to_season
        FROM team_source_mappings
        WHERE source_name = 'patreon'
        """,
        connection,
    )

    mappings["source_team_name"] = (
        mappings["source_team_name"].astype(str)
    )

    frame = players.merge(
        mappings,
        on="source_team_name",
        how="left",
    )

    valid = (
        (
            frame["valid_from_season"].isna()
            | (frame["season"] >= frame["valid_from_season"])
        )
        &
        (
            frame["valid_to_season"].isna()
            | (frame["season"] <= frame["valid_to_season"])
        )
    )

    frame = frame.loc[valid].copy()

    missing = frame["team_id"].isna()

    if missing.any():
        examples = (
            frame.loc[
                missing,
                ["source_team_name", "season"],
            ]
            .drop_duplicates()
            .head(10)
            .to_dict("records")
        )

        raise ValueError(
            f"{missing.sum()} Patreon rows could not map to canonical teams. "
            f"Examples: {examples}"
        )

    frame["team_id"] = frame["team_id"].astype(int)

    return frame


def attach_player_mappings(
    connection: sqlite3.Connection,
    players: pd.DataFrame,
) -> pd.DataFrame:
    mappings = pd.read_sql_query(
        """
        SELECT
            player_id AS canonical_player_id,
            CAST(source_player_id AS TEXT) AS source_player_id,
            season,
            team_id
        FROM player_source_mappings
        WHERE source_name = 'patreon'
        """,
        connection,
    )

    frame = players.merge(
        mappings,
        on=[
            "source_player_id",
            "season",
            "team_id",
        ],
        how="left",
        validate="many_to_one",
    )

    missing = frame["canonical_player_id"].isna()

    if missing.any():
        missing_players = (
            frame.loc[
                missing,
                [
                    "source_player_id",
                    "player_name",
                    "season",
                    "team_id",
                ],
            ]
            .drop_duplicates()
        )

        LOGGER.warning(
            "Skipping %s Patreon player rows with no canonical player mapping.",
            int(missing.sum()),
        )

        for row in missing_players.itertuples(index=False):
            LOGGER.warning(
                "Unmapped player: %s | %s | season=%s | team_id=%s",
                row.source_player_id,
                row.player_name,
                row.season,
                row.team_id,
            )

        frame = frame.loc[~missing].copy()

    frame["player_id"] = frame["canonical_player_id"].astype(str)

    return frame


def teamsheet_exists(
    connection: sqlite3.Connection,
    fixture_id: str,
    team_id: int,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM teamsheets
        WHERE fixture_id = ?
          AND team_id = ?
        LIMIT 1
        """,
        (
            fixture_id,
            team_id,
        ),
    ).fetchone()

    return row is not None


def get_fixture_side(
    connection: sqlite3.Connection,
    fixture_id: str,
    team_id: int,
) -> str:
    row = connection.execute(
        """
        SELECT home_team_id, away_team_id
        FROM fixtures
        WHERE fixture_id = ?
        """,
        (fixture_id,),
    ).fetchone()

    if row is None:
        raise ValueError(f"Fixture not found: {fixture_id}")

    home_team_id, away_team_id = row

    if team_id == int(home_team_id):
        return "home"

    if team_id == int(away_team_id):
        return "away"

    raise ValueError(
        f"Team {team_id} is not part of fixture {fixture_id}"
    )


def build_teamsheet_rows(
    connection: sqlite3.Connection,
    players: pd.DataFrame,
    season: int,
) -> pd.DataFrame:
    season_players = players.loc[
        players["season"] == season
    ].copy()

    if season_players.empty:
        LOGGER.info("No Patreon player rows found for season %s.", season)
        return pd.DataFrame()

    output_rows: list[dict] = []

    grouped = season_players.groupby(
        ["fixture_id", "team_id"],
        sort=True,
    )

    for (fixture_id, team_id), group in grouped:
        fixture_id = str(fixture_id)
        team_id = int(team_id)

        if teamsheet_exists(
            connection=connection,
            fixture_id=fixture_id,
            team_id=team_id,
        ):
            LOGGER.info(
                "Skipping %s team_id=%s - teamsheet already exists.",
                fixture_id,
                team_id,
            )
            continue

        LOGGER.info(
            "Building Patreon teamsheet for %s team_id=%s (%s players)",
            fixture_id,
            team_id,
            len(group),
        )

        group = (
            group
            .sort_values("source_lineup_order")
            .head(17)
            .copy()
        )

        group["lineup_order"] = range(1, len(group) + 1)

        side = get_fixture_side(
            connection=connection,
            fixture_id=fixture_id,
            team_id=team_id,
        )

        for row in group.itertuples(index=False):
            position_id = pd.to_numeric(
                row.position_id,
                errors="coerce",
            )

            position = (
                str(int(position_id))
                if pd.notna(position_id)
                else None
            )

            output_rows.append(
                {
                    "fixture_id": fixture_id,
                    "season": int(row.season),
                    "team_id": team_id,
                    "player_id": str(row.player_id),
                    "side": side,
                    "position": position,
                    "lineup_order": int(row.lineup_order),
                    "is_starting": int(row.lineup_order <= 13),
                    "source_name": SOURCE_NAME,
                    "source_match_id": str(row.source_fixture_id),
                    "source_url": (
                        str(row.fixture_url)
                        if pd.notna(row.fixture_url)
                        else None
                    ),
                }
            )
    if not output_rows:
        return pd.DataFrame()

    return pd.DataFrame.from_records(output_rows)


def build_missing_player_rows(
    connection: sqlite3.Connection,
    players: pd.DataFrame,
) -> pd.DataFrame:
    existing = pd.read_sql_query(
        """
        SELECT
            player_id,
            season,
            team_id
        FROM players
        """,
        connection,
    )

    candidates = (
        players[
            [
                "player_id",
                "player_name",
                "season",
                "team_id",
                "source_player_id",
                "position_id",
            ]
        ]
        .copy()
    )

    candidates["player_id"] = candidates["player_id"].astype(str)

    # One player/team/season row.
    candidates = (
        candidates
        .sort_values("position_id")
        .groupby(
            ["player_id", "season", "team_id"],
            as_index=False,
        )
        .agg(
            player_name=("player_name", "first"),
            source_player_id=("source_player_id", "first"),
            primary_position=("position_id", "first"),
        )
    )

    candidates = candidates.merge(
        existing,
        on=["player_id", "season", "team_id"],
        how="left",
        indicator=True,
    )

    missing = candidates.loc[
        candidates["_merge"] == "left_only"
    ].copy()

    if missing.empty:
        return pd.DataFrame()

    missing["active"] = 1
    missing["source_name"] = SOURCE_NAME

    return missing[
        [
            "player_id",
            "player_name",
            "season",
            "team_id",
            "primary_position",
            "active",
            "source_name",
            "source_player_id",
        ]
    ]


def upsert_teamsheets(
    connection: sqlite3.Connection,
    teamsheets: pd.DataFrame,
) -> int:
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


def upsert_players(
    connection: sqlite3.Connection,
    players: pd.DataFrame,
) -> int:
    if players.empty:
        return 0

    return upsert_dataframe(
        connection=connection,
        dataframe=players,
        table_name="players",
        columns=[
            "player_id",
            "player_name",
            "season",
            "team_id",
            "primary_position",
            "active",
            "source_name",
            "source_player_id",
        ],
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

def ingest_season(
    connection: sqlite3.Connection,
    season: int,
) -> int:
    players = load_patreon_players()

    players = attach_fixture_mappings(
        connection=connection,
        players=players,
    )

    players = attach_team_mappings(
        connection=connection,
        players=players,
    )

    players = attach_player_mappings(
        connection=connection,
        players=players,
    )

    missing_players = build_missing_player_rows(
        connection=connection,
        players=players,
    )

    player_rows_saved = upsert_players(
        connection=connection,
        players=missing_players,
    )
    if player_rows_saved:
        LOGGER.info(
            "Inserted/updated %s missing Patreon player-season-team rows.",
            player_rows_saved,
        )

    teamsheets = build_teamsheet_rows(
        connection=connection,
        players=players,
        season=season,
    )

    if teamsheets.empty:
        LOGGER.info(
            "No new Patreon teamsheets to ingest for %s.",
            season,
        )
        return 0

    fixture_count = teamsheets["fixture_id"].nunique()

    invalid = pd.read_sql_query(
        """
        SELECT
            p.player_id,
            p.season,
            p.team_id
        FROM players p
        """,
        connection,
    )

    check = teamsheets.merge(
        invalid,
        on=["player_id", "season", "team_id"],
        how="left",
        indicator=True,
    )

    missing_players = check.loc[
        check["_merge"] == "left_only",
        [
            "fixture_id",
            "team_id",
            "player_id",
            "season",
            "source_match_id",
        ],
    ]

    if not missing_players.empty:
        print("Teamsheet rows with no matching players row:")
        print(
            missing_players
            .drop_duplicates()
            .to_string(index=False)
        )

        raise ValueError(
            f"{len(missing_players)} teamsheet rows "
            "have no matching canonical players row."
        )

    bad = teamsheets.loc[
        ~teamsheets["lineup_order"].between(1, 17)
    ]

    if not bad.empty:
        print("BAD LINEUP ORDERS:")
        print(
            bad[
                [
                    "fixture_id",
                    "team_id",
                    "player_id",
                    "lineup_order",
                    "position",
                ]
            ].to_string(index=False)
        )
        raise ValueError(
            f"{len(bad)} rows have invalid lineup_order"
        )

    print(
        "lineup_order range:",
        teamsheets["lineup_order"].min(),
        teamsheets["lineup_order"].max(),
    )

    rows_saved = upsert_teamsheets(
        connection=connection,
        teamsheets=teamsheets,
    )

    LOGGER.info(
        "Season %s: saved %s teamsheet rows across %s fixtures.",
        season,
        rows_saved,
        fixture_count,
    )

    return rows_saved


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fill missing canonical teamsheets using Patreon player data."
        )
    )

    parser.add_argument(
        "--season",
        type=int,
        required=True,
        help="Season to ingest, for example 2026.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    with get_connection() as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        rows_saved = ingest_season(
            connection=connection,
            season=args.season,
        )

        connection.commit()

    LOGGER.info(
        "Finished Patreon teamsheet ingestion. Saved %s rows.",
        rows_saved,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    main()