from __future__ import annotations

import logging
import sqlite3
from typing import Any

LOGGER = logging.getLogger(__name__)

SOURCE_NAME = "rugby_league_project"


SUPER_LEAGUE_TEAMS: dict[int, set[str]] = {
    2010: {
        "Bradford Bulls",
        "Castleford Tigers",
        "Catalans Dragons",
        "Crusaders RL",
        "Harlequins RL",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Salford City Reds",
        "St Helens",
        "Wakefield Trinity Wildcats",
        "Warrington Wolves",
        "Wigan Warriors",
    },
    2011: {
        "Bradford Bulls",
        "Castleford Tigers",
        "Catalans Dragons",
        "Crusaders RL",
        "Harlequins RL",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Salford City Reds",
        "St Helens",
        "Wakefield Trinity Wildcats",
        "Warrington Wolves",
        "Wigan Warriors",
    },
    2012: {
        "Bradford Bulls",
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "London Broncos",
        "Salford City Reds",
        "St Helens",
        "Wakefield Trinity Wildcats",
        "Warrington Wolves",
        "Widnes Vikings",
        "Wigan Warriors",
    },
    2013: {
        "Bradford Bulls",
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "London Broncos",
        "Salford City Reds",
        "St Helens",
        "Wakefield Trinity Wildcats",
        "Warrington Wolves",
        "Widnes Vikings",
        "Wigan Warriors",
    },
    2014: {
        "Bradford Bulls",
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "London Broncos",
        "Salford Red Devils",
        "St Helens",
        "Wakefield Trinity Wildcats",
        "Warrington Wolves",
        "Widnes Vikings",
        "Wigan Warriors",
    },
    2015: {
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Salford Red Devils",
        "St Helens",
        "Wakefield Trinity Wildcats",
        "Warrington Wolves",
        "Widnes Vikings",
        "Wigan Warriors",
    },
    2016: {
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Salford Red Devils",
        "St Helens",
        "Wakefield Trinity Wildcats",
        "Warrington Wolves",
        "Widnes Vikings",
        "Wigan Warriors",
    },
    2017: {
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Leeds Rhinos",
        "Leigh Centurions",
        "Salford Red Devils",
        "St Helens",
        "Wakefield Trinity",
        "Warrington Wolves",
        "Widnes Vikings",
        "Wigan Warriors",
    },
    2018: {
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Salford Red Devils",
        "St Helens",
        "Wakefield Trinity",
        "Warrington Wolves",
        "Widnes Vikings",
        "Wigan Warriors",
    },
    2019: {
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "London Broncos",
        "Salford Red Devils",
        "St Helens",
        "Wakefield Trinity",
        "Warrington Wolves",
        "Wigan Warriors",
    },
    2020: {
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Salford Red Devils",
        "St Helens",
        "Toronto Wolfpack",
        "Wakefield Trinity",
        "Warrington Wolves",
        "Wigan Warriors",
    },
    2021: {
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Leigh Centurions",
        "Salford Red Devils",
        "St Helens",
        "Wakefield Trinity",
        "Warrington Wolves",
        "Wigan Warriors",
    },
    2022: {
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Salford Red Devils",
        "St Helens",
        "Toulouse Olympique",
        "Wakefield Trinity",
        "Warrington Wolves",
        "Wigan Warriors",
    },
    2023: {
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Leigh Leopards",
        "Salford Red Devils",
        "St Helens",
        "Wakefield Trinity",
        "Warrington Wolves",
        "Wigan Warriors",
    },
    2024: {
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Leigh Leopards",
        "London Broncos",
        "Salford Red Devils",
        "St Helens",
        "Warrington Wolves",
        "Wigan Warriors",
    },
    2025: {
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Leigh Leopards",
        "Salford Red Devils",
        "St Helens",
        "Wakefield Trinity",
        "Warrington Wolves",
        "Wigan Warriors",
    },
    2026: {
        "Bradford Bulls",
        "Castleford Tigers",
        "Catalans Dragons",
        "Huddersfield Giants",
        "Hull FC",
        "Hull Kingston Rovers",
        "Leeds Rhinos",
        "Leigh Leopards",
        "St Helens",
        "Toulouse Olympique",
        "Wakefield Trinity",
        "Warrington Wolves",
        "Wigan Warriors",
        "York Knights",
    },
}


# Source names which should map to an existing canonical club name.
KNOWN_CANONICAL_ALIASES: dict[str, str] = {
    "Leigh Centurions": "Leigh Leopards",
    "Salford City Reds": "Salford Red Devils",
    "Wakefield Trinity Wildcats": "Wakefield Trinity",
}


def filter_super_league_matches(
    matches: list[dict[str, Any]],
    season: int,
) -> list[dict[str, Any]]:
    valid_teams = SUPER_LEAGUE_TEAMS.get(season)

    if valid_teams is None:
        raise ValueError(f"No Super League team list configured for {season}")

    retained: list[dict[str, Any]] = []

    for match in matches:
        home_team = match["home_team_name"]
        away_team = match["away_team_name"]

        if home_team in valid_teams and away_team in valid_teams:
            retained.append(match)
        else:
            LOGGER.debug(
                "Removing non-Super-League match: %s vs %s",
                home_team,
                away_team,
            )

    removed_count = len(matches) - len(retained)

    LOGGER.info(
        "Season %s: retained %s league matches and removed %s other matches",
        season,
        len(retained),
        removed_count,
    )

    return retained


def resolve_team_id(
    connection: sqlite3.Connection,
    source_team_name: str,
    season: int,
    source_name: str = SOURCE_NAME,
) -> int | None:
    row = connection.execute(
        """
        SELECT team_id
        FROM team_source_mappings
        WHERE source_name = ?
          AND source_team_name = ?
          AND (
              valid_from_season IS NULL
              OR valid_from_season <= ?
          )
          AND (
              valid_to_season IS NULL
              OR valid_to_season >= ?
          )
        ORDER BY valid_from_season DESC
        LIMIT 1
        """,
        (
            source_name,
            source_team_name,
            season,
            season,
        ),
    ).fetchone()

    if row is None:
        return None

    return int(row[0])


def find_canonical_team_id(
    connection: sqlite3.Connection,
    canonical_name: str,
) -> int | None:
    row = connection.execute(
        """
        SELECT team_id
        FROM teams
        WHERE canonical_name = ?
        LIMIT 1
        """,
        (canonical_name,),
    ).fetchone()

    if row is None:
        return None

    return int(row[0])


def create_team(
    connection: sqlite3.Connection,
    canonical_name: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO teams (
            canonical_name
        )
        VALUES (?)
        """,
        (canonical_name,),
    )

    team_id = cursor.lastrowid

    if team_id is None:
        raise RuntimeError(f"Failed to create team {canonical_name!r}")

    LOGGER.warning(
        "Created new canonical team: %s -> team_id %s",
        canonical_name,
        team_id,
    )

    return int(team_id)


def create_team_mapping(
    connection: sqlite3.Connection,
    team_id: int,
    source_team_name: str,
    season: int,
    source_name: str = SOURCE_NAME,
) -> None:
    connection.execute(
        """
        INSERT INTO team_source_mappings (
            team_id,
            source_name,
            source_team_name,
            valid_from_season,
            valid_to_season
        )
        VALUES (?, ?, ?, ?, NULL)
        """,
        (
            team_id,
            source_name,
            source_team_name,
            season,
        ),
    )

    LOGGER.warning(
        "Created new team mapping: %s / %s -> team_id %s",
        source_name,
        source_team_name,
        team_id,
    )


def get_or_create_team_id(
    connection: sqlite3.Connection,
    source_team_name: str,
    season: int,
    source_name: str = SOURCE_NAME,
) -> int:
    existing_team_id = resolve_team_id(
        connection=connection,
        source_team_name=source_team_name,
        season=season,
        source_name=source_name,
    )

    if existing_team_id is not None:
        return existing_team_id

    canonical_name = KNOWN_CANONICAL_ALIASES.get(
        source_team_name,
        source_team_name,
    )

    team_id = find_canonical_team_id(
        connection=connection,
        canonical_name=canonical_name,
    )

    if team_id is None:
        team_id = create_team(
            connection=connection,
            canonical_name=canonical_name,
        )

    create_team_mapping(
        connection=connection,
        team_id=team_id,
        source_team_name=source_team_name,
        season=season,
        source_name=source_name,
    )

    return team_id


def apply_team_ids(
    connection: sqlite3.Connection,
    matches: list[dict[str, Any]],
    create_missing: bool = True,
) -> list[dict[str, Any]]:
    mapped_matches: list[dict[str, Any]] = []

    for match in matches:
        season = int(match["season"])

        if create_missing:
            home_team_id = get_or_create_team_id(
                connection=connection,
                source_team_name=match["home_team_name"],
                season=season,
            )
            away_team_id = get_or_create_team_id(
                connection=connection,
                source_team_name=match["away_team_name"],
                season=season,
            )

        else:
            home_team_id = resolve_team_id(
                connection=connection,
                source_team_name=match["home_team_name"],
                season=season,
            )
            away_team_id = resolve_team_id(
                connection=connection,
                source_team_name=match["away_team_name"],
                season=season,
            )

            if home_team_id is None:
                raise ValueError(
                    "No team mapping found for "
                    f"{match['home_team_name']!r} "
                    f"in season {season}"
                )

            if away_team_id is None:
                raise ValueError(
                    "No team mapping found for "
                    f"{match['away_team_name']!r} "
                    f"in season {season}"
                )

        mapped_matches.append(
            {
                **match,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "source_name": SOURCE_NAME,
                "source_match_id": None,
            }
        )

    return mapped_matches
