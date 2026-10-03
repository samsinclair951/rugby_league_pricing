from __future__ import annotations

import argparse
import sqlite3
from datetime import date

import pandas as pd

from src.rugby_league_pricing.database.connection import get_connection


def check_fixture_readiness(
    connection: sqlite3.Connection,
    start_date: str,
    end_date: str,
    recent_fixture_count: int = 5,
) -> pd.DataFrame:
    """
    Check whether upcoming fixtures have the baseline data required to build
    expected lineups and expected-lineup strength adjustments.
    """

    query = """
    WITH upcoming_teams AS (
        SELECT
            f.fixture_id,
            f.match_date,
            f.season,
            f.home_team_id AS team_id,
            f.away_team_id AS opponent_team_id,
            'home' AS side
        FROM fixtures f
        WHERE DATE(f.match_date) BETWEEN ? AND ?

        UNION ALL

        SELECT
            f.fixture_id,
            f.match_date,
            f.season,
            f.away_team_id AS team_id,
            f.home_team_id AS opponent_team_id,
            'away' AS side
        FROM fixtures f
        WHERE DATE(f.match_date) BETWEEN ? AND ?
    ),

    recent_completed AS (
        SELECT
            ut.fixture_id AS upcoming_fixture_id,
            ut.team_id,
            pf.fixture_id AS past_fixture_id,
            pf.match_date,

            ROW_NUMBER() OVER (
                PARTITION BY ut.fixture_id, ut.team_id
                ORDER BY pf.match_date DESC
            ) AS recency_rank

        FROM upcoming_teams ut

        JOIN fixtures pf
            ON (
                pf.home_team_id = ut.team_id
                OR pf.away_team_id = ut.team_id
            )
           AND pf.match_date < ut.match_date

        JOIN results r
            ON r.fixture_id = pf.fixture_id
    ),

    recent_n AS (
        SELECT *
        FROM recent_completed
        WHERE recency_rank <= ?
    ),

    recent_summary AS (
        SELECT
            r.upcoming_fixture_id,
            r.team_id,

            COUNT(DISTINCT r.past_fixture_id)
                AS recent_results_count,

            COUNT(
                DISTINCT CASE
                    WHEN ts.fixture_id IS NOT NULL
                    THEN r.past_fixture_id
                END
            ) AS recent_teamsheet_count,

            MAX(
                CASE
                    WHEN ts.fixture_id IS NOT NULL
                    THEN r.match_date
                END
            ) AS latest_teamsheet_date

        FROM recent_n r

        LEFT JOIN teamsheets ts
            ON ts.fixture_id = r.past_fixture_id
           AND ts.team_id = r.team_id

        GROUP BY
            r.upcoming_fixture_id,
            r.team_id
    )

    SELECT
        ut.fixture_id,
        ut.match_date,
        ut.side,

        t.canonical_name AS team,
        opp.canonical_name AS opponent,

        COALESCE(rs.recent_results_count, 0)
            AS recent_results,

        COALESCE(rs.recent_teamsheet_count, 0)
            AS recent_teamsheets,

        rs.latest_teamsheet_date,

        CASE
            WHEN EXISTS (
                SELECT 1
                FROM strength_multipliers sm
                WHERE sm.fixture_id = ut.fixture_id
                  AND sm.team_id = ut.team_id
                  AND sm.version_type = 'baseline'
            )
            THEN 'YES'
            ELSE 'NO'
        END AS baseline_multiplier,

        CASE
            WHEN EXISTS (
                SELECT 1
                FROM expected_scores es
                WHERE es.fixture_id = ut.fixture_id
                AND (
                    es.home_team_id = ut.team_id
                    OR es.away_team_id = ut.team_id
                )
            )
            THEN 'YES'
            ELSE 'NO'
        END AS expected_score,

        CASE
            WHEN EXISTS (
                SELECT 1
                FROM teamsheets ts
                WHERE ts.fixture_id = ut.fixture_id
                  AND ts.team_id = ut.team_id
            )
            THEN 'YES'
            ELSE 'NO'
        END AS current_teamsheet,

        CASE
            WHEN COALESCE(rs.recent_results_count, 0) >= ?
             AND COALESCE(rs.recent_teamsheet_count, 0) >= 3

             AND EXISTS (
                 SELECT 1
                 FROM strength_multipliers sm
                 WHERE sm.fixture_id = ut.fixture_id
                   AND sm.team_id = ut.team_id
                   AND sm.version_type = 'baseline'
             )

             AND EXISTS (
                SELECT 1
                FROM expected_scores es
                WHERE es.fixture_id = ut.fixture_id
                AND (
                    es.home_team_id = ut.team_id
                    OR es.away_team_id = ut.team_id
                )
            )
            
            THEN 'READY'
            ELSE 'CHECK'
        END AS readiness

    FROM upcoming_teams ut

    JOIN teams t
        ON t.team_id = ut.team_id

    JOIN teams opp
        ON opp.team_id = ut.opponent_team_id

    LEFT JOIN recent_summary rs
        ON rs.upcoming_fixture_id = ut.fixture_id
       AND rs.team_id = ut.team_id

    ORDER BY
        ut.match_date,
        ut.fixture_id,
        ut.side
    """

    return pd.read_sql_query(
        query,
        connection,
        params=[
            start_date,
            end_date,
            start_date,
            end_date,
            recent_fixture_count,
            recent_fixture_count,
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check data readiness for upcoming fixtures."
    )

    parser.add_argument(
        "--start-date",
        default=date.today().isoformat(),
    )

    parser.add_argument(
        "--end-date",
        required=True,
    )

    parser.add_argument(
        "--recent-fixtures",
        type=int,
        default=5,
    )

    args = parser.parse_args()

    with get_connection() as connection:
        result = check_fixture_readiness(
            connection=connection,
            start_date=args.start_date,
            end_date=args.end_date,
            recent_fixture_count=args.recent_fixtures,
        )

    if result.empty:
        print(
            f"No fixtures found between "
            f"{args.start_date} and {args.end_date}."
        )
        return

    print()
    print(
        result.to_string(
            index=False,
        )
    )
    print()

    ready = (result["readiness"] == "READY").sum()
    total = len(result)

    print(f"READY: {ready}/{total} team-fixtures")

    if ready == total:
        print("✓ All fixtures ready for expected-lineup generation.")
    else:
        print("⚠ Some fixtures need attention.")


if __name__ == "__main__":
    main()