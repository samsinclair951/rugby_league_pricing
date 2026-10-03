from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]

DATABASE_PATH = REPO_ROOT / "data" / "rugby_league_pricing.db"

PLAYER_FILES = [
    REPO_ROOT
    / "data"
    / "raw"
    / "patreon"
    / "players"
    / "sl_player_data_19_25.csv",
    REPO_ROOT
    / "data"
    / "raw"
    / "patreon"
    / "players"
    / "2026_sl_player_data.csv",
]

SOURCE_NAME = "patreon"


# Patreon source name -> canonical team name.
#
# Season ranges are optional and useful where a source name changes over time.
TEAM_MAPPINGS = [
    {
        "source_team_name": "Bradford Bulls",
        "canonical_name": "Bradford Bulls",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Castleford Tigers",
        "canonical_name": "Castleford Tigers",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Catalans Dragons",
        "canonical_name": "Catalans Dragons",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Huddersfield Giants",
        "canonical_name": "Huddersfield Giants",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Hull FC",
        "canonical_name": "Hull FC",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Hull Kingston Rovers",
        "canonical_name": "Hull Kingston Rovers",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Leeds Rhinos",
        "canonical_name": "Leeds Rhinos",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Leigh Centurions",
        "canonical_name": "Leigh Leopards",
        "valid_from_season": 2019,
        "valid_to_season": 2022,
    },
    {
        "source_team_name": "Leigh Leopards",
        "canonical_name": "Leigh Leopards",
        "valid_from_season": 2023,
        "valid_to_season": None,
    },
    {
        "source_team_name": "London Broncos",
        "canonical_name": "London Broncos",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Salford Red Devils",
        "canonical_name": "Salford Red Devils",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "St Helens",
        "canonical_name": "St Helens",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Toronto Wolfpack",
        "canonical_name": "Toronto Wolfpack",
        "valid_from_season": 2019,
        "valid_to_season": 2020,
    },
    {
        "source_team_name": "Toulouse Olympique",
        "canonical_name": "Toulouse Olympique",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Wakefield Trinity",
        "canonical_name": "Wakefield Trinity",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Warrington Wolves",
        "canonical_name": "Warrington Wolves",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "Wigan Warriors",
        "canonical_name": "Wigan Warriors",
        "valid_from_season": 2019,
        "valid_to_season": None,
    },
    {
        "source_team_name": "York RLFC",
        "canonical_name": "York Knights",
        "valid_from_season": 2026,
        "valid_to_season": None,
    },
]


def load_patreon_team_names() -> set[str]:
    """Return unique Patreon team names found in the raw player files."""
    teams: set[str] = set()

    for path in PLAYER_FILES:
        if not path.exists():
            raise FileNotFoundError(f"Patreon player file not found: {path}")

        frame = pd.read_csv(
            path,
            usecols=["team_id", "opposition_id"],
        )

        for column in ("team_id", "opposition_id"):
            values = (
                frame[column]
                .dropna()
                .astype(str)
                .str.strip()
            )

            teams.update(values)

    return teams


def get_canonical_teams(
    connection: sqlite3.Connection,
) -> dict[str, int]:
    """Return canonical team name -> team_id."""
    rows = connection.execute(
        """
        SELECT team_id, canonical_name
        FROM teams
        """
    ).fetchall()

    return {
        canonical_name: team_id
        for team_id, canonical_name in rows
    }


def validate_mappings(
    patreon_team_names: set[str],
    canonical_teams: dict[str, int],
) -> None:
    """Fail before writing if source or canonical mappings are incomplete."""
    configured_source_names = {
        mapping["source_team_name"]
        for mapping in TEAM_MAPPINGS
    }

    missing_source_names = sorted(
        patreon_team_names - configured_source_names
    )

    if missing_source_names:
        raise ValueError(
            "Missing Patreon team mappings for: "
            + ", ".join(missing_source_names)
        )

    missing_canonical_names = sorted(
        {
            mapping["canonical_name"]
            for mapping in TEAM_MAPPINGS
            if mapping["canonical_name"] not in canonical_teams
        }
    )

    if missing_canonical_names:
        raise ValueError(
            "Canonical teams do not exist in teams table: "
            + ", ".join(missing_canonical_names)
        )


def upsert_team_source_mappings(
    connection: sqlite3.Connection,
    canonical_teams: dict[str, int],
    patreon_team_names: set[str],
) -> None:
    """Insert or update Patreon team source mappings."""
    for mapping in TEAM_MAPPINGS:
        if mapping["source_team_name"] not in patreon_team_names:
            continue

        team_id = canonical_teams[mapping["canonical_name"]]

        connection.execute(
            """
            INSERT INTO team_source_mappings (
                team_id,
                source_name,
                source_team_name,
                valid_from_season,
                valid_to_season
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (
                source_name,
                source_team_name,
                valid_from_season
            )
            DO UPDATE SET
                team_id = excluded.team_id,
                valid_to_season = excluded.valid_to_season,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                team_id,
                SOURCE_NAME,
                mapping["source_team_name"],
                mapping["valid_from_season"],
                mapping["valid_to_season"],
            ),
        )


def get_team_id(
    connection: sqlite3.Connection,
    source_team_name: str,
    season: int,
) -> int:
    """Resolve a Patreon team name to the canonical team_id."""

    row = connection.execute(
        """
        SELECT team_id
        FROM team_source_mappings
        WHERE source_name = ?
          AND source_team_name = ?
          AND valid_from_season <= ?
          AND (
              valid_to_season IS NULL
              OR valid_to_season >= ?
          )
        ORDER BY valid_from_season DESC
        LIMIT 1
        """,
        (
            SOURCE_NAME,
            source_team_name,
            season,
            season,
        ),
    ).fetchone()

    if row is None:
        raise ValueError(
            f"No Patreon mapping found for "
            f"{source_team_name!r} in season {season}"
        )

    return int(row[0])


def apply_team_ids(
    connection: sqlite3.Connection,
    matches: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Attach canonical team IDs to Patreon match records."""

    for match in matches:
        season = int(match["season"])

        match["home_team_id"] = get_team_id(
            connection,
            str(match["home_team"]),
            season,
        )

        match["away_team_id"] = get_team_id(
            connection,
            str(match["away_team"]),
            season,
        )

    return matches


def main() -> None:
    patreon_team_names = load_patreon_team_names()

    print(
        f"Found {len(patreon_team_names)} Patreon team names."
    )

    for team_name in sorted(patreon_team_names):
        print(f"  - {team_name}")

    with sqlite3.connect(DATABASE_PATH) as connection:
        canonical_teams = get_canonical_teams(connection)

        validate_mappings(
            patreon_team_names=patreon_team_names,
            canonical_teams=canonical_teams,
        )

        upsert_team_source_mappings(
            connection=connection,
            canonical_teams=canonical_teams,
            patreon_team_names=patreon_team_names,
        )

        connection.commit()

    print()
    print("Patreon team mappings updated successfully.")


if __name__ == "__main__":
    main()