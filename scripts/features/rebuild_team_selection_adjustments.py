"""Backfill historical team-selection feature rows."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd
import time

from rugby_league_pricing.features.team_lineups.adjustment_upsert import (
    upsert_team_selection_adjustments,
)
from rugby_league_pricing.features.team_lineups.strength import (
    build_team_lineup_strength,
)
from streamlit import connection


REPO_ROOT = Path(__file__).resolve().parents[2]

DATABASE_PATH = (
    REPO_ROOT
    / "data"
    / "rugby_league_pricing.db"
)

VERSION_TYPE = "confirmed_line_up"


def load_fixtures(
    connection: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Load historical fixtures with teamsheets available
    for both sides.
    """

    sql = """
        SELECT
            f.fixture_id,
            f.match_date,
            f.season,
            f.home_team_id,
            f.away_team_id

        FROM fixtures f

        JOIN results r
            ON r.fixture_id = f.fixture_id

        WHERE (
            SELECT COUNT(DISTINCT ts.team_id)
            FROM teamsheets ts
            WHERE ts.fixture_id = f.fixture_id
        ) = 2
    """

    params: list[str] = []

    if start_date is not None:
        sql += """
            AND f.match_date >= ?
        """
        params.append(start_date)

    if end_date is not None:
        sql += """
            AND f.match_date <= ?
        """
        params.append(end_date)

    sql += """
        ORDER BY
            f.match_date,
            f.fixture_id
    """

    return pd.read_sql_query(
        sql,
        connection,
        params=params,
        parse_dates=["match_date"],
    )


def build_fixture_adjustments(
    connection: sqlite3.Connection,
    fixture: pd.Series,
) -> pd.DataFrame:
    """Build raw player-selection features for both teams."""

    fixture_id = str(
        fixture["fixture_id"]
    )

    home_team_id = int(
        fixture["home_team_id"]
    )

    away_team_id = int(
        fixture["away_team_id"]
    )

    team_rows = [
        {
            "team_id": home_team_id,
            "opponent_id": away_team_id,
            "is_home": 1,
        },
        {
            "team_id": away_team_id,
            "opponent_id": home_team_id,
            "is_home": 0,
        },
    ]

    rows: list[pd.DataFrame] = []

    for team in team_rows:
        strength = build_team_lineup_strength(
            connection=connection,
            fixture_id=fixture_id,
            team_id=team["team_id"],
            version_type=VERSION_TYPE,
        )

        strength["opponent_id"] = (
            team["opponent_id"]
        )

        strength["is_home"] = (
            team["is_home"]
        )

        # Historical backfill stores raw features only.
        # Model outputs get generated later.
        strength["player_log_adjustment"] = 0.0
        strength["score_adjustment_factor"] = 1.0
        strength["model_version"] = None

        rows.append(strength)

    return pd.concat(
        rows,
        ignore_index=True,
    )


def rebuild_team_selection_adjustments(
    connection: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Backfill historical confirmed-lineup feature rows."""

    fixtures = load_fixtures(
        connection,
        start_date=start_date,
        end_date=end_date,
    )

    if fixtures.empty:
        raise ValueError(
            "No fixtures with complete historical "
            "teamsheets were found."
        )

    total = len(fixtures)

    print(
        f"Found {total:,} fixtures "
        "with teamsheets for both teams."
    )

    completed = 0
    skipped = 0

    for i, fixture in fixtures.iterrows():
        started = time.perf_counter()
        fixture_id = fixture["fixture_id"]
        match_date = fixture["match_date"]

        print(
            f"[{i + 1}/{total}] Processing "
            f"{match_date} | {fixture_id}...",
            flush=True,
        )

        try:
            adjustment_rows = build_fixture_adjustments(
                connection=connection,
                fixture=fixture,
            )

            upsert_team_selection_adjustments(
                connection=connection,
                adjustments=adjustment_rows,
            )

            completed += 1

            print(
                f"[{i + 1}/{total}] ✓ Completed {fixture_id}",
                flush=True,
            )

        except ValueError as exc:
            skipped += 1

            print(
                f"[{i + 1}/{total}] ✗ Skipped {fixture_id}: {exc}",
                flush=True,
            )
        elapsed = time.perf_counter() - started

        print(
            f"[{i + 1}/{total}] ✓ Completed {fixture_id} "
            f"in {elapsed:.2f}s",
            flush=True,
        )

    connection.commit()

    print()
    print(
        f"Completed: {completed:,}"
    )
    print(
        f"Skipped:   {skipped:,}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
    )

    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
    )

    args = parser.parse_args()

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DATABASE_PATH}"
        )

    with sqlite3.connect(
        DATABASE_PATH,
        timeout=30.0,
    ) as connection:
        connection.execute(
            "PRAGMA busy_timeout = 30000"
        )
        rebuild_team_selection_adjustments(
            connection,
            start_date=args.start_date,
            end_date=args.end_date,
        )


if __name__ == "__main__":
    main()