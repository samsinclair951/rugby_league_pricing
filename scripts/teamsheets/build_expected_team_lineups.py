from __future__ import annotations

import argparse

from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.features.team_lineups.build_expected import (
    save_expected_lineups_for_match_date,
)


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--match-date",
        required=True,
        help="Match date to rebuild in YYYY-MM-DD format.",
    )

    args = parser.parse_args()

    with get_connection() as connection:
        count = save_expected_lineups_for_match_date(
            connection=connection,
            match_date=args.match_date,
        )

        connection.commit()

    print(
        f"Saved {count} expected lineup rows "
        f"for match date {args.match_date}"
    )


if __name__ == "__main__":
    main()