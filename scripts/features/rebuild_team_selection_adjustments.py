"""Backfill historical team-selection feature rows."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd
import time

from rugby_league_pricing.features.strength_multipliers.blended_final import (
    predict_from_stored_model,
)
from rugby_league_pricing.features.strength_multipliers.model_store import (
    load_latest_player_blend_model,
)
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

DEFAULT_VERSION_TYPE = "confirmed_line_up"


def load_fixtures(
    connection: sqlite3.Connection,
    *,
    version_type: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:

    sql = """
        SELECT
            f.fixture_id,
            f.match_date,
            f.season,
            f.home_team_id,
            f.away_team_id
        FROM fixtures f
        WHERE f.season = 2026
    """

    params: list[object] = []

    if version_type == "confirmed_line_up":
        sql += """
            AND EXISTS (
                SELECT 1
                FROM results r
                WHERE r.fixture_id = f.fixture_id
            )
            AND (
                SELECT COUNT(DISTINCT ts.team_id)
                FROM teamsheets ts
                WHERE ts.fixture_id = f.fixture_id
            ) = 2
        """

    else:
        sql += """
            AND (
                SELECT COUNT(DISTINCT etl.team_id)
                FROM expected_team_lineups etl
                WHERE etl.fixture_id = f.fixture_id
                  AND etl.version_type = ?
            ) = 2
        """
        params.append(version_type)

    if start_date is not None:
        sql += " AND DATE(f.match_date) >= ?"
        params.append(start_date)

    if end_date is not None:
        sql += " AND DATE(f.match_date) <= ?"
        params.append(end_date)

    sql += """
        ORDER BY f.match_date, f.fixture_id
    """

    return pd.read_sql_query(
        sql,
        connection,
        params=params,
        parse_dates=["match_date"],
    )


def fixture_adjustments_exist(
    connection: sqlite3.Connection,
    fixture_id: str,
    home_team_id: int,
    away_team_id: int,
    version_type: str,
) -> bool:
    row = connection.execute(
        """
        SELECT COUNT(DISTINCT team_id)
        FROM team_selection_adjustments
        WHERE fixture_id = ?
          AND version_type = ?
          AND team_id IN (?, ?)
        """,
        (
            fixture_id,
            version_type,
            home_team_id,
            away_team_id,
        ),
    ).fetchone()

    return row[0] == 2


def build_fixture_adjustments(
    connection: sqlite3.Connection,
    fixture: pd.Series,
    version_type: str,
) -> pd.DataFrame:
    """Build and predict player-selection adjustments for both teams."""

    fixture_id = str(
        fixture["fixture_id"]
    )

    match_date = pd.Timestamp(
        fixture["match_date"]
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
            version_type=version_type,
        )

        strength["opponent_id"] = (
            team["opponent_id"]
        )

        strength["is_home"] = (
            team["is_home"]
        )

        rows.append(strength)

    lineup_strength = pd.concat(
        rows,
        ignore_index=True,
    )

    stored_model = load_latest_player_blend_model(
        connection=connection,
        before_date=match_date,
    )

    adjustments = predict_from_stored_model(
        lineup_strength=lineup_strength,
        stored_model=stored_model,
    )

    return adjustments


def rebuild_team_selection_adjustments(
    connection: sqlite3.Connection,
    *,
    version_type: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Backfill historical confirmed-lineup feature rows."""

    fixtures = load_fixtures(
        connection,
        version_type=version_type,
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

        if fixture_adjustments_exist(
            connection,
            fixture_id=fixture["fixture_id"],
            home_team_id=fixture["home_team_id"],
            away_team_id=fixture["away_team_id"],
            version_type=version_type,
        ):
            print(f"Skipping {fixture['fixture_id']} - adjustments already exist for both teams.")
            continue
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
                version_type=version_type,
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
            "--version-type",
            type=str,
            default="confirmed_line_up",
            choices=[
                "confirmed_line_up",
                "pre_preview_expected_line_up",
                "preview_expected_line_up",
            ],
        )

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
            version_type=args.version_type,
            start_date=args.start_date,
            end_date=args.end_date,
        )


if __name__ == "__main__":
    main()