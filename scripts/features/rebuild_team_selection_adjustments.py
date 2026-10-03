"""Backfill historical team-selection feature rows."""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path

import pandas as pd

from rugby_league_pricing.features.strength_multipliers.blended_final import (
    DEFAULT_RIDGE_ALPHA,
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
from scripts.features.rebuild_player_blend_models import (
    train_and_store_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

DATABASE_PATH = (
    REPO_ROOT
    / "data"
    / "rugby_league_pricing.db"
)

DEFAULT_VERSION_TYPE = "confirmed_line_up"


def _fixture_has_tournament_id(
    connection: sqlite3.Connection,
) -> bool:
    columns = pd.read_sql_query(
        "PRAGMA table_info(fixtures)",
        connection,
    )

    return "tournament_id" in set(columns["name"].astype(str))


def _fixture_rounds_table_exists(
    connection: sqlite3.Connection,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'fixture_rounds'
        LIMIT 1
        """
    ).fetchone()

    return row is not None


def load_fixtures(
    connection: sqlite3.Connection,
    *,
    version_type: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:

    tournament_column = (
        "f.tournament_id"
        if _fixture_has_tournament_id(connection)
        else "0 AS tournament_id"
    )

    round_columns = "NULL AS round_number, NULL AS round_start_date, NULL AS round_end_date"
    round_join = ""

    if _fixture_rounds_table_exists(connection):
        round_columns = (
            "fr.round_number AS round_number, "
            "fr.round_start_date AS round_start_date, "
            "fr.round_end_date AS round_end_date"
        )
        round_join = """
        LEFT JOIN fixture_rounds fr
            ON fr.fixture_id = f.fixture_id
        """

    sql = f"""
        SELECT
            f.fixture_id,
            f.match_date,
            f.season,
            {tournament_column},
            f.home_team_id,
            f.away_team_id,
            {round_columns}
        FROM fixtures f
        {round_join}
        WHERE 1 = 1
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


def adjustments_exist(
    connection: sqlite3.Connection,
    fixture_id: str,
    version_type: str,
) -> bool:
    row = connection.execute(
        """
        SELECT COUNT(DISTINCT team_id)
        FROM team_selection_adjustments
        WHERE fixture_id = ?
          AND version_type = ?
        """,
        (
            fixture_id,
            version_type,
        ),
    ).fetchone()

    return int(row[0]) == 2


def rebuild_team_selection_adjustments(
    connection: sqlite3.Connection,
    *,
    version_type: str,
    start_date: str | None = None,
    end_date: str | None = None,
    run_player_blend_after_round: bool = False,
    ridge_alpha: float = DEFAULT_RIDGE_ALPHA,
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

    fixture_lookup = fixtures.set_index("fixture_id", drop=False)
    processed = 0

    if "tournament_id" not in fixtures.columns:
        fixtures["tournament_id"] = 0
    if "round_number" not in fixtures.columns:
        fixtures["round_number"] = pd.NA
    if "round_start_date" not in fixtures.columns:
        fixtures["round_start_date"] = pd.NaT
    if "round_end_date" not in fixtures.columns:
        fixtures["round_end_date"] = pd.NaT

    fixtures["round_number"] = pd.to_numeric(
        fixtures["round_number"],
        errors="coerce",
    )
    fixtures["round_start_date"] = pd.to_datetime(
        fixtures["round_start_date"],
        errors="coerce",
    )
    fixtures["round_end_date"] = pd.to_datetime(
        fixtures["round_end_date"],
        errors="coerce",
    )

    if fixtures["round_number"].isna().any():
        missing_count = int(fixtures["round_number"].isna().sum())
        raise ValueError(
            "Missing fixture round assignment for "
            f"{missing_count} fixture(s). Run "
            "scripts/rounds/rebuild_round_assignment.py for the requested "
            "window before rebuilding team_selection_adjustments."
        )

    grouped_rounds = fixtures.sort_values(
        ["season", "tournament_id", "round_number", "fixture_id"]
    ).groupby(["season", "tournament_id", "round_number"], sort=False)

    for (season, tournament_id, round_number), round_group in grouped_rounds:
        print(
            f"Round {int(round_number)} | season {int(season)} | "
            f"tournament {int(tournament_id)} | fixtures {len(round_group)}",
            flush=True,
        )

        for _, round_row in round_group.iterrows():
            fixture_id = str(round_row["fixture_id"])
            fixture = fixture_lookup.loc[fixture_id]

            processed += 1
            i = processed - 1

            started = time.perf_counter()
            match_date = fixture["match_date"]

            if version_type == "baseline" and adjustments_exist(
                connection=connection,
                fixture_id=fixture_id,
                version_type=version_type,
            ):
                skipped += 1

                print(
                    f"[{i + 1}/{total}] Skipping {fixture_id} - baseline adjustments already exist.",
                    flush=True,
                )
                continue

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

                # Persist each successful fixture immediately so
                # interrupted runs retain completed progress.
                connection.commit()

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

        if run_player_blend_after_round and version_type == "confirmed_line_up":
            round_end_date = pd.Timestamp(round_group["round_end_date"].max())
            try:
                model_version = train_and_store_snapshot(
                    connection,
                    trained_through_date=round_end_date,
                    ridge_alpha=ridge_alpha,
                )
                print(
                    f"Trained player blend model after round {int(round_number)}: "
                    f"{model_version}",
                    flush=True,
                )
            except ValueError as exc:
                print(
                    f"Skipped player blend model retrain after round {int(round_number)}: {exc}",
                    flush=True,
                )

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

    parser.add_argument(
        "--run-player-blend-after-round",
        action="store_true",
        default=True,
        help=(
            "After each computed round completes, retrain a player blend "
            "snapshot through that round end date."
        ),
    )

    parser.add_argument(
        "--ridge-alpha",
        type=float,
        default=DEFAULT_RIDGE_ALPHA,
        help="Ridge alpha used when retraining player blend snapshots.",
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
            run_player_blend_after_round=args.run_player_blend_after_round,
            ridge_alpha=args.ridge_alpha,
        )


if __name__ == "__main__":
    main()