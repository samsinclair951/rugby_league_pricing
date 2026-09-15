from __future__ import annotations

import argparse

from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.features.team_lineups.build_expected import (
    save_expected_lineups_for_fixture,
)


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--fixture-id",
        required=True,
    )

    args = parser.parse_args()

    with get_connection() as connection:
        count = save_expected_lineups_for_fixture(
            connection=connection,
            fixture_id=args.fixture_id,
        )

        connection.commit()

    print(
        f"Saved {count} expected lineup rows "
        f"for fixture {args.fixture_id}"
    )


if __name__ == "__main__":
    main()