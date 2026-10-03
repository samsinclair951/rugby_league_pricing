from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

from scripts.fixtures.rugby_league_project.ingest_fixtures import build_fixture_id


LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATABASE_PATH = REPO_ROOT / "data" / "rugby_league_pricing.db"


def get_team_id(
    connection: sqlite3.Connection,
    team_name: str,
) -> int:
    row = connection.execute(
        """
        SELECT team_id
        FROM teams
        WHERE canonical_name = ?
        """,
        (team_name,),
    ).fetchone()

    if row is None:
        raise ValueError(f"Unknown team: {team_name}")

    return int(row[0])


def get_fixture_id_tables(
    connection: sqlite3.Connection,
) -> list[str]:
    """
    Return every table containing a fixture_id column.
    """
    tables = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()

    fixture_tables = []

    for (table_name,) in tables:
        columns = connection.execute(
            f'PRAGMA table_info("{table_name}")'
        ).fetchall()

        column_names = {column[1] for column in columns}

        if "fixture_id" in column_names:
            fixture_tables.append(table_name)

    return fixture_tables


def update_fixture(
    *,
    season: int,
    home_team: str,
    away_team: str,
    old_date: str,
    new_date: str,
) -> None:
    connection = sqlite3.connect(DATABASE_PATH)

    try:
        home_team_id = get_team_id(connection, home_team)
        away_team_id = get_team_id(connection, away_team)

        old_fixture_id = build_fixture_id(
            match_date=old_date,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
        )

        new_fixture_id = build_fixture_id(
            match_date=new_date,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
        )

        fixture = connection.execute(
            """
            SELECT
                fixture_id,
                match_date,
                home_team_id,
                away_team_id
            FROM fixtures
            WHERE fixture_id = ?
              AND season = ?
            """,
            (old_fixture_id, season),
        ).fetchone()

        if fixture is None:
            raise ValueError(
                "Fixture not found:\n"
                f"  {old_date} | {home_team} vs {away_team}\n"
                f"  fixture_id={old_fixture_id}"
            )

        existing_new = connection.execute(
            """
            SELECT fixture_id
            FROM fixtures
            WHERE fixture_id = ?
            """,
            (new_fixture_id,),
        ).fetchone()

        if existing_new is not None:
            raise ValueError(
                f"Destination fixture already exists: {new_fixture_id}"
            )

        fixture_tables = get_fixture_id_tables(connection)

        LOGGER.info(
            "Updating %s vs %s: %s -> %s",
            home_team,
            away_team,
            old_date,
            new_date,
        )

        LOGGER.info(
            "Fixture ID: %s -> %s",
            old_fixture_id,
            new_fixture_id,
        )

        # We need to update the parent fixture ID and all dependent
        # fixture_id references together.
        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")

        try:
            connection.execute("BEGIN")

            # Update every dependent table first.
            for table_name in fixture_tables:
                if table_name == "fixtures":
                    continue

                cursor = connection.execute(
                    f"""
                    UPDATE "{table_name}"
                    SET fixture_id = ?
                    WHERE fixture_id = ?
                    """,
                    (new_fixture_id, old_fixture_id),
                )

                if cursor.rowcount:
                    LOGGER.info(
                        "Updated %s row(s) in %s",
                        cursor.rowcount,
                        table_name,
                    )

            # Finally update canonical fixture row.
            connection.execute(
                """
                UPDATE fixtures
                SET fixture_id = ?,
                    match_date = ?
                WHERE fixture_id = ?
                """,
                (
                    new_fixture_id,
                    new_date,
                    old_fixture_id,
                ),
            )

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.execute("PRAGMA foreign_keys = ON")

        violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if violations:
            raise RuntimeError(
                "Foreign key violations found after fixture update:\n"
                + "\n".join(str(row) for row in violations)
            )

        LOGGER.info("Fixture updated successfully.")

    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manually move a fixture to a corrected date."
    )

    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--old-date", required=True)
    parser.add_argument("--new-date", required=True)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    update_fixture(
        season=args.season,
        home_team=args.home,
        away_team=args.away,
        old_date=args.old_date,
        new_date=args.new_date,
    )


if __name__ == "__main__":
    main()