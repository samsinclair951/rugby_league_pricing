import argparse
import sqlite3
from collections import Counter

import pandas as pd

from scripts.features.rebuild_player_blend_models import DATABASE_PATH


def ensure_fixture_rounds_table(
    connection: sqlite3.Connection,
) -> None:
    """Create fixture_rounds storage used by round-based workflows."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS fixture_rounds (
            fixture_id TEXT PRIMARY KEY,
            season INTEGER NOT NULL,
            tournament_id INTEGER NOT NULL,
            round_number INTEGER NOT NULL,
            round_start_date TEXT NOT NULL,
            round_end_date TEXT NOT NULL,
            round_source TEXT NOT NULL,
            has_replay_team INTEGER NOT NULL DEFAULT 0
                CHECK (has_replay_team IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (fixture_id)
                REFERENCES fixtures(fixture_id),

            UNIQUE (
                season,
                tournament_id,
                round_number,
                fixture_id
            )
        );

        CREATE INDEX IF NOT EXISTS idx_fixture_rounds_lookup
            ON fixture_rounds(
                season,
                tournament_id,
                round_number
            );

        CREATE INDEX IF NOT EXISTS idx_fixture_rounds_fixture
            ON fixture_rounds(fixture_id);
        """
    )


def load_fixtures(
    connection: sqlite3.Connection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    sql = """
        SELECT
            f.fixture_id,
            f.match_date,
            f.season,
            COALESCE(f.tournament_id, 0) AS tournament_id,
            f.home_team_id,
            f.away_team_id
        FROM fixtures f
        WHERE 1 = 1
    """

    params: list[object] = []

    if start_date is not None:
        sql += " AND DATE(f.match_date) >= ?"
        params.append(start_date)

    if end_date is not None:
        sql += " AND DATE(f.match_date) <= ?"
        params.append(end_date)

    sql += " ORDER BY f.match_date, f.fixture_id"

    return pd.read_sql_query(
        sql,
        connection,
        params=params,
        parse_dates=["match_date"],
    )

def assign_fixture_rounds(
    fixtures: pd.DataFrame,
) -> pd.DataFrame:
    """
    Assign rounds by contiguous fixture windows.

    Heuristic:
    - Rounds run in chronological order per season/tournament.
    - Start a new round on Thursday if current round already has 5+ fixtures.
    - Force a split if a round reaches 9 fixtures.
    """
    if fixtures.empty:
        return pd.DataFrame(
            columns=[
                "fixture_id",
                "season",
                "tournament_id",
                "round_number",
                "round_start_date",
                "round_end_date",
                "round_source",
                "has_replay_team",
            ]
        )

    ordered = fixtures.copy()
    ordered["match_date"] = pd.to_datetime(ordered["match_date"]).dt.normalize()
    ordered["season"] = pd.to_numeric(ordered["season"], errors="coerce").fillna(0).astype(int)
    tournament_values = (
        ordered["tournament_id"]
        if "tournament_id" in ordered.columns
        else pd.Series([0] * len(ordered), index=ordered.index)
    )
    ordered["tournament_id"] = pd.to_numeric(
        tournament_values,
        errors="coerce",
    ).fillna(0).astype(int)

    ordered = ordered.sort_values(
        ["season", "tournament_id", "match_date", "fixture_id"]
    ).reset_index(drop=True)

    rows: list[dict[str, object]] = []

    for (season, tournament_id), group in ordered.groupby(["season", "tournament_id"], sort=False):
        round_number = 0
        current: list[dict[str, object]] = []

        for rec in group.to_dict(orient="records"):
            match_date = pd.Timestamp(rec["match_date"]).normalize()
            weekday = int(match_date.dayofweek)  # Monday=0 ... Sunday=6

            should_start_new_round = False
            if current:
                if weekday == 3 and len(current) >= 5:
                    should_start_new_round = True
                if len(current) >= 9:
                    should_start_new_round = True

            if should_start_new_round:
                rows.extend(
                    _build_round_rows(
                        current=current,
                        season=season,
                        tournament_id=tournament_id,
                        round_number=round_number,
                    )
                )
                current = []

            if not current:
                round_number += 1

            current.append(
                {
                    "fixture_id": str(rec["fixture_id"]),
                    "match_date": match_date,
                    "home_team_id": int(rec["home_team_id"]),
                    "away_team_id": int(rec["away_team_id"]),
                }
            )

        rows.extend(
            _build_round_rows(
                current=current,
                season=season,
                tournament_id=tournament_id,
                round_number=round_number,
            )
        )

    return pd.DataFrame(rows)


def _build_round_rows(
    *,
    current: list[dict[str, object]],
    season: int,
    tournament_id: int,
    round_number: int,
) -> list[dict[str, object]]:
    """Build persisted round rows for one computed round window."""
    if not current:
        return []

    team_counts: Counter[int] = Counter()
    for rec in current:
        team_counts[int(rec["home_team_id"])] += 1
        team_counts[int(rec["away_team_id"])] += 1

    start_date = min(pd.Timestamp(rec["match_date"]) for rec in current)
    end_date = max(pd.Timestamp(rec["match_date"]) for rec in current)

    output: list[dict[str, object]] = []
    for rec in current:
        has_replay_team = int(
            team_counts[int(rec["home_team_id"])] > 1
            or team_counts[int(rec["away_team_id"])] > 1
        )

        output.append(
            {
                "fixture_id": str(rec["fixture_id"]),
                "season": int(season),
                "tournament_id": int(tournament_id),
                "round_number": int(round_number),
                "round_start_date": start_date.strftime("%Y-%m-%d"),
                "round_end_date": end_date.strftime("%Y-%m-%d"),
                "round_source": "heuristic",
                "has_replay_team": has_replay_team,
            }
        )

    return output


def upsert_fixture_rounds(
    connection: sqlite3.Connection,
    fixture_rounds: pd.DataFrame,
) -> int:
    if fixture_rounds.empty:
        return 0

    rows = [
        (
            str(row["fixture_id"]),
            int(row["season"]),
            int(row["tournament_id"]),
            int(row["round_number"]),
            str(row["round_start_date"]),
            str(row["round_end_date"]),
            str(row["round_source"]),
            int(row["has_replay_team"]),
        )
        for _, row in fixture_rounds.iterrows()
    ]

    connection.executemany(
        """
        INSERT INTO fixture_rounds (
            fixture_id,
            season,
            tournament_id,
            round_number,
            round_start_date,
            round_end_date,
            round_source,
            has_replay_team
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (fixture_id)
        DO UPDATE SET
            season = excluded.season,
            tournament_id = excluded.tournament_id,
            round_number = excluded.round_number,
            round_start_date = excluded.round_start_date,
            round_end_date = excluded.round_end_date,
            round_source = excluded.round_source,
            has_replay_team = excluded.has_replay_team,
            updated_at = CURRENT_TIMESTAMP
        """,
        rows,
    )

    return len(rows)

def rebuild_round_assignment(
    connection: sqlite3.Connection,
    fixtures: pd.DataFrame,
) -> None:
    ensure_fixture_rounds_table(connection)
    fixture_rounds = assign_fixture_rounds(fixtures)
    upsert_fixture_rounds(connection, fixture_rounds)
    connection.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", type=str, default=None)
    parser.add_argument("--end-date", type=str, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with sqlite3.connect(
        DATABASE_PATH,
        timeout=30.0,
    ) as connection:
        connection.execute(
            "PRAGMA busy_timeout = 30000"
        )
        fixtures = load_fixtures(
            connection,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        rebuild_round_assignment(
            connection,
            fixtures,
        )


if __name__ == "__main__":
    main()