from __future__ import annotations

import sqlite3
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DATABASE_PATH = REPO_ROOT / "data" / "rugby_league_pricing.db"

SOURCE_NAME = "rugby_league_project"


def validate_database_path() -> None:
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database does not exist: {DATABASE_PATH}"
        )


def validate_database(
    connection: sqlite3.Connection,
) -> None:
    required_tables = {
        "fixtures",
        "fixture_source_mappings",
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
            "Database is missing required tables: "
            f"{sorted(missing_tables)}"
        )

    fixture_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(fixtures)"
        ).fetchall()
    }

    required_columns = {
        "fixture_id",
        "source_match_id",
    }

    missing_columns = (
        required_columns - fixture_columns
    )

    if missing_columns:
        raise RuntimeError(
            "fixtures table is missing required columns: "
            f"{sorted(missing_columns)}"
        )


def load_fixture_mappings(
    connection: sqlite3.Connection,
) -> list[tuple[str, str]]:
    rows = connection.execute(
        """
        SELECT
            fixture_id,
            source_match_id
        FROM fixtures
        WHERE source_match_id IS NOT NULL
        """
    ).fetchall()

    mappings: list[tuple[str, str]] = []

    for fixture_id, source_match_id in rows:
        source_fixture_id = str(
            source_match_id
        ).strip()

        if not source_fixture_id:
            continue

        mappings.append(
            (
                str(fixture_id),
                source_fixture_id,
            )
        )

    return mappings


def validate_source_ids(
    mappings: list[tuple[str, str]],
) -> None:
    seen: dict[str, int] = {}

    for fixture_id, source_fixture_id in mappings:
        existing_fixture_id = seen.get(
            source_fixture_id
        )

        if (
            existing_fixture_id is not None
            and existing_fixture_id != fixture_id
        ):
            raise ValueError(
                "Duplicate Rugby League Project "
                "source fixture ID found: "
                f"{source_fixture_id} maps to "
                f"fixture_id {existing_fixture_id} "
                f"and {fixture_id}"
            )

        seen[source_fixture_id] = fixture_id


def upsert_fixture_source_mappings(
    connection: sqlite3.Connection,
    mappings: list[tuple[str, str]],
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
                fixture_id,
                SOURCE_NAME,
                source_fixture_id,
            )
            for fixture_id, source_fixture_id
            in mappings
        ],
    )


def main() -> None:
    validate_database_path()

    with sqlite3.connect(
        DATABASE_PATH
    ) as connection:
        validate_database(connection)

        mappings = load_fixture_mappings(
            connection
        )

        print(
            f"Found {len(mappings)} fixtures with "
            "Rugby League Project source_match_id values."
        )

        validate_source_ids(mappings)

        upsert_fixture_source_mappings(
            connection=connection,
            mappings=mappings,
        )

        connection.commit()

    print(
        f"Inserted/updated {len(mappings)} "
        "Rugby League Project fixture mappings."
    )


if __name__ == "__main__":
    main()