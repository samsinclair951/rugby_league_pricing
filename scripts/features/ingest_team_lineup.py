"""Ingest a team-lineup file and produce player-adjusted strength multipliers.

Usage
-----
    python -m scripts.features.ingest_team_lineup \
        --file data/team_lineups/round_10_previews.csv

The file must be a CSV or JSON with the columns:
    fixture_id, team_id, player_id, player_name, position_id, version_type

version_type must be one of:
    pre_preview_expected_line_up  – early-week expected team
    preview_expected_line_up      – updated after preview
    confirmed_line_up             – final team news

After ingestion the expected_scores table will automatically use the latest
version for each fixture/team the next time rebuild_expected_scores is run.
"""

from __future__ import annotations

import argparse

from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.features.team_lineups import ingest_lineup_file


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest a team-lineup file and update strength multipliers."
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Path to the lineup CSV or JSON file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    with get_connection() as connection:
        lineup_rows, multiplier_rows = ingest_lineup_file(
            connection=connection,
            path=args.file,
        )

    print(f"Stored {lineup_rows} lineup rows.")
    print(f"Stored {multiplier_rows} adjusted strength-multiplier rows.")


if __name__ == "__main__":
    main()
