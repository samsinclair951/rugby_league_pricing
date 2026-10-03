from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]

DATABASE_PATH = REPO_ROOT / "data" / "rugby_league_pricing.db"

RESULTS_FILES = [
    REPO_ROOT
    / "data"
    / "raw"
    / "patreon"
    / "results"
    / "sl_results_data_19_25.csv",
    
    REPO_ROOT
    / "data"
    / "raw"
    / "patreon"
    / "results"
    / "2026_sl_fixture_data.csv",
]

SOURCE_NAME = "patreon"

FIXTURE_DATE_CORRECTIONS = {
    "10218": "2020-03-08",
}


def validate_paths() -> None:
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database does not exist: {DATABASE_PATH}"
        )

    for file_path in RESULTS_FILES:
        if not file_path.exists():
            raise FileNotFoundError(
                f"Patreon results file does not exist: {file_path}"
            )


def get_table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {row[1] for row in rows}


def validate_database(connection: sqlite3.Connection) -> None:
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

    existing_tables = {row[0] for row in rows}

    missing_tables = required_tables - existing_tables

    if missing_tables:
        raise RuntimeError(
            f"Database is missing required tables: "
            f"{sorted(missing_tables)}"
        )


def load_patreon_fixtures() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for path in RESULTS_FILES:
        print(f"Loading Patreon fixtures from: {path}")

        frame = pd.read_csv(
            path,
            usecols=[
                "fixture_id",
                "fixture_date",
                "home_team",
                "away_team",
                "neutral_venue",
            ],
        )

        frame["source_file"] = path.name

        frames.append(frame)

    if not frames:
        raise RuntimeError(
            "No Patreon results files were loaded."
        )

    frame = pd.concat(
        frames,
        ignore_index=True,
    )

    frame = frame.rename(
        columns={
            "fixture_id": "source_fixture_id",
        }
    )

    frame["fixture_date"] = pd.to_datetime(
        frame["fixture_date"],
        errors="raise",
    ).dt.normalize()

    corrected_dates = pd.to_datetime(
        pd.Series(FIXTURE_DATE_CORRECTIONS),
        errors="raise",
    ).dt.normalize()

    frame["fixture_date"] = (
        frame["source_fixture_id"]
        .astype(str)
        .map(corrected_dates)
        .fillna(frame["fixture_date"])
    )

    frame["season"] = frame["fixture_date"].dt.year

    for column in (
        "home_team",
        "away_team",
    ):
        frame[column] = (
            frame[column]
            .astype(str)
            .str.strip()
        )

    duplicate_source_ids = frame[
        frame["source_fixture_id"].duplicated(
            keep=False
        )
    ]

    if not duplicate_source_ids.empty:
        raise ValueError(
            "Duplicate Patreon fixture IDs found:\n"
            + duplicate_source_ids.to_string(
                index=False
            )
        )

    return frame


def load_team_source_mappings(
    connection: sqlite3.Connection,
) -> pd.DataFrame:
    frame = pd.read_sql_query(
        """
        SELECT
            team_id,
            source_team_name,
            valid_from_season,
            valid_to_season
        FROM team_source_mappings
        WHERE source_name = ?
        """,
        connection,
        params=(SOURCE_NAME,),
    )

    if frame.empty:
        raise RuntimeError(
            "No Patreon team mappings found. "
            "Run teams_mapping.py first."
        )

    return frame


def resolve_team_id(
    source_team_name: str,
    season: int,
    mappings: pd.DataFrame,
) -> int:
    candidates = mappings[
        mappings["source_team_name"].eq(source_team_name)
    ].copy()

    if candidates.empty:
        raise ValueError(
            f"No Patreon team mapping found for "
            f"{source_team_name!r}"
        )

    candidates = candidates[
        (
            candidates["valid_from_season"].isna()
            | (
                candidates["valid_from_season"]
                <= season
            )
        )
        & (
            candidates["valid_to_season"].isna()
            | (
                candidates["valid_to_season"]
                >= season
            )
        )
    ]

    if len(candidates) == 0:
        raise ValueError(
            f"No valid Patreon mapping for "
            f"{source_team_name!r} in {season}"
        )

    if len(candidates) > 1:
        raise ValueError(
            f"Multiple valid Patreon mappings for "
            f"{source_team_name!r} in {season}"
        )

    return int(candidates.iloc[0]["team_id"])


def resolve_team_ids(
    frame: pd.DataFrame,
    mappings: pd.DataFrame,
) -> pd.DataFrame:
    frame = frame.copy()

    frame["home_team_id"] = frame.apply(
        lambda row: resolve_team_id(
            source_team_name=row["home_team"],
            season=int(row["season"]),
            mappings=mappings,
        ),
        axis=1,
    )

    frame["away_team_id"] = frame.apply(
        lambda row: resolve_team_id(
            source_team_name=row["away_team"],
            season=int(row["season"]),
            mappings=mappings,
        ),
        axis=1,
    )

    return frame


def detect_fixture_date_column(
    connection: sqlite3.Connection,
) -> str:
    columns = get_table_columns(
        connection,
        "fixtures",
    )

    candidates = [
        "fixture_date",
        "match_date",
        "date",
    ]

    for candidate in candidates:
        if candidate in columns:
            return candidate

    raise RuntimeError(
        "Could not determine fixture date column. "
        f"Fixtures columns are: {sorted(columns)}"
    )


def load_canonical_fixtures(
    connection: sqlite3.Connection,
) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT
            fixture_id,
            match_date,
            home_team_id,
            away_team_id,
            competition_stage_id
        FROM fixtures
        """,
        connection,
    )


def match_fixtures(
    patreon: pd.DataFrame,
    canonical: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    matched: list[dict] = []
    unresolved: list[dict] = []

    canonical = canonical.copy()

    canonical["match_date"] = pd.to_datetime(
        canonical["match_date"],
        errors="raise",
    ).dt.normalize()

    for row in patreon.itertuples(index=False):
        exact_fixture_id = (
            f"{row.fixture_date.strftime('%Y-%m-%d')}_"
            f"{row.home_team_id}_"
            f"{row.away_team_id}"
        )

        exact = canonical[
            canonical["fixture_id"].eq(exact_fixture_id)
        ]

        if len(exact) == 1:
            matched.append(
                {
                    "fixture_id": exact_fixture_id,
                    "source_fixture_id": str(row.source_fixture_id),
                    "match_type": "exact",
                    "fixture_date": row.fixture_date,
                    "home_team": row.home_team,
                    "away_team": row.away_team,
                }
            )
            continue

        # Reversed orientation on the same date.
        reversed_candidates = canonical[
            canonical["match_date"].eq(row.fixture_date)
            & canonical["home_team_id"].eq(row.away_team_id)
            & canonical["away_team_id"].eq(row.home_team_id)
        ]

        if len(reversed_candidates) == 1:
            reversed_row = reversed_candidates.iloc[0]

            neutral_venue = int(
                getattr(row, "neutral_venue", 0) or 0
            )

            is_non_regular_stage = (
                reversed_row["competition_stage_id"] is not None
                and int(reversed_row["competition_stage_id"]) != 1
            )

            if neutral_venue == 1 or is_non_regular_stage:
                matched.append(
                    {
                        "fixture_id": str(
                            reversed_row["fixture_id"]
                        ),
                        "source_fixture_id": str(
                            row.source_fixture_id
                        ),
                        "match_type": "reversed",
                        "fixture_date": row.fixture_date,
                        "home_team": row.home_team,
                        "away_team": row.away_team,
                    }
                )
                continue

        unresolved.append(
            {
                "source_fixture_id": row.source_fixture_id,
                "fixture_date": row.fixture_date,
                "season": row.season,
                "home_team": row.home_team,
                "away_team": row.away_team,
                "home_team_id": row.home_team_id,
                "away_team_id": row.away_team_id,
            }
        )

    return (
        pd.DataFrame(matched),
        pd.DataFrame(unresolved),
    )


def upsert_fixture_source_mappings(
    connection: sqlite3.Connection,
    mappings: pd.DataFrame,
) -> None:
    connection.executemany(
        """
        INSERT INTO fixture_source_mappings (
            fixture_id,
            source_name,
            source_fixture_id
        )
        VALUES (?, ?, ?)

        ON CONFLICT (
            source_name,
            source_fixture_id
        )
        DO UPDATE SET
            fixture_id = excluded.fixture_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        [
            (
                str(row.fixture_id),
                SOURCE_NAME,
                str(row.source_fixture_id),
            )
            for row in mappings.itertuples(
                index=False
            )
        ],
    )


def main() -> None:
    validate_paths()

    patreon_fixtures = load_patreon_fixtures()

    print(
        f"Loaded {len(patreon_fixtures)} "
        "Patreon fixtures."
    )

    with sqlite3.connect(DATABASE_PATH) as connection:
        validate_database(connection)

        team_mappings = load_team_source_mappings(
            connection
        )

        patreon_fixtures = resolve_team_ids(
            frame=patreon_fixtures,
            mappings=team_mappings,
        )

        canonical = load_canonical_fixtures(
            connection
        )

        matched, unresolved = match_fixtures(
            patreon=patreon_fixtures,
            canonical=canonical,
        )

        print()
        print(
            f"Matched:    {len(matched)}"
        )
        print(
            f"Unresolved: {len(unresolved)}"
        )

        reversed_matches = matched[
            matched["match_type"] == "reversed"
        ]

        if not reversed_matches.empty:
            print()
            print("Reversed home/away mappings:")
            print(
                reversed_matches[
                    [
                        "source_fixture_id",
                        "fixture_id",
                        "home_team",
                        "away_team",
                    ]
                ].to_string(index=False)
            )

        if not matched.empty:
            print()
            print("Match types:")
            print(
                matched["match_type"]
                .value_counts()
                .to_string()
            )

        if not unresolved.empty:
            print()
            print("Unresolved Patreon fixtures:")
            print(
                unresolved.to_string(index=False)
            )

        upsert_fixture_source_mappings(
            connection=connection,
            mappings=matched,
        )

        connection.commit()

    print()
    print(
        f"Inserted/updated "
        f"{len(matched)} Patreon fixture mappings."
    )


if __name__ == "__main__":
    main()