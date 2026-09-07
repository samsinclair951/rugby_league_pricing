import sqlite3
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]

DATABASE_PATH = (
    REPO_ROOT
    / "data"
    / "rugby_league_pricing.db"
)

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


SOURCE_FIXTURE_IDS = [
    10081,
    10082,
    10134,
    10218,
    10250,
    10281,
    10330,
    10401,
    10403,
    10405,
    10404,
    10422,
    10704,
    10734,
]


def main() -> None:
    patreon = pd.concat(
        [
            pd.read_csv(path)
            for path in RESULTS_FILES
        ],
        ignore_index=True,
    )

    patreon = patreon[
        patreon["fixture_id"].isin(
            SOURCE_FIXTURE_IDS
        )
    ].copy()

    with sqlite3.connect(DATABASE_PATH) as connection:
        teams = pd.read_sql_query(
            """
            SELECT
                team_id,
                canonical_name
            FROM teams
            """,
            connection,
        )

        mappings = pd.read_sql_query(
            """
            SELECT
                tsm.team_id,
                tsm.source_team_name
            FROM team_source_mappings tsm
            WHERE tsm.source_name = 'patreon'
            """,
            connection,
        )

        fixtures = pd.read_sql_query(
            """
            SELECT
                f.fixture_id,
                f.season,
                f.match_date,
                f.home_team_id,
                f.away_team_id,
                f.source_match_id,
                f.competition_stage_id,
                f.venue,
                ht.canonical_name AS home_team,
                at.canonical_name AS away_team
            FROM fixtures f
            JOIN teams ht
                ON ht.team_id = f.home_team_id
            JOIN teams at
                ON at.team_id = f.away_team_id
            """,
            connection,
        )

    team_map = dict(
        zip(
            mappings["source_team_name"],
            mappings["team_id"],
        )
    )

    for row in patreon.itertuples(index=False):
        season = pd.Timestamp(
            row.fixture_date
        ).year

        home_team_id = team_map[row.home_team]
        away_team_id = team_map[row.away_team]

        candidates = fixtures[
            (fixtures["season"] == season)
            & (
                (
                    (fixtures["home_team_id"] == home_team_id)
                    & (fixtures["away_team_id"] == away_team_id)
                )
                |
                (
                    (fixtures["home_team_id"] == away_team_id)
                    & (fixtures["away_team_id"] == home_team_id)
                )
            )
        ].copy()

        candidates["date_diff_days"] = (
            pd.to_datetime(candidates["match_date"])
            - pd.Timestamp(row.fixture_date)
        ).dt.days

        candidates = candidates.sort_values(
            by="date_diff_days",
            key=lambda x: x.abs(),
        )

        print()
        print("=" * 90)
        print(
            f"PATREON {row.fixture_id}: "
            f"{row.fixture_date} | "
            f"{row.home_team} v {row.away_team}"
        )

        if hasattr(row, "fixture_round"):
            print(
                f"Round: {row.fixture_round} | "
                f"Neutral: {row.neutral_venue}"
            )

        print()
        print("RLP candidates:")

        if candidates.empty:
            print("  NONE")
            continue

        print(
            candidates[
                [
                    "fixture_id",
                    "match_date",
                    "source_match_id",
                    "home_team",
                    "away_team",
                    "competition_stage_id",
                    "venue",
                    "date_diff_days",
                ]
            ].to_string(index=False)
        )


if __name__ == "__main__":
    main()