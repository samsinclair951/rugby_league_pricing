from __future__ import annotations

import argparse

import pandas as pd

from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.features.strength_multipliers.blended_final import (
    build_final_strength_multipliers,
)
from rugby_league_pricing.features.strength_multipliers.upsert import (
    upsert_strength_multipliers,
)


def rebuild_lineup_strength_multipliers(
    fixture_id: str,
    version_type: str,
) -> int:
    with get_connection() as connection:
        baseline = pd.read_sql_query(
            """
            SELECT *
            FROM strength_multipliers
            WHERE fixture_id = ?
              AND version_type = 'baseline'
            ORDER BY team_id
            """,
            connection,
            params=(fixture_id,),
        )

        if baseline.empty:
            raise ValueError(
                f"No baseline strength multipliers found for {fixture_id}"
            )

        adjustments = pd.read_sql_query(
            """
            SELECT *
            FROM team_selection_adjustments
            WHERE fixture_id = ?
              AND version_type = ?
            ORDER BY team_id
            """,
            connection,
            params=(
                fixture_id,
                version_type,
            ),
        )

        if adjustments.empty:
            raise ValueError(
                f"No {version_type} team-selection adjustments "
                f"found for {fixture_id}"
            )

        if baseline["team_id"].nunique() != 2:
            raise ValueError(
                f"Expected 2 baseline team rows for {fixture_id}, "
                f"found {baseline['team_id'].nunique()}"
            )

        if adjustments["team_id"].nunique() != 2:
            raise ValueError(
                f"Expected 2 adjustment rows for {fixture_id}, "
                f"found {adjustments['team_id'].nunique()}"
            )

        final = build_final_strength_multipliers(
            baseline=baseline,
            adjustments=adjustments,
            version_type=version_type,
        )

        rows_saved = upsert_strength_multipliers(
            connection=connection,
            strength_multipliers=final,
            version_type=version_type,
        )

        connection.commit()

    return rows_saved


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--fixture-id",
        required=True,
    )

    parser.add_argument(
        "--version-type",
        required=True,
        choices=[
            "pre_preview_expected_line_up",
            "preview_expected_line_up",
            "confirmed_line_up",
        ],
    )

    args = parser.parse_args()

    rows_saved = rebuild_lineup_strength_multipliers(
        fixture_id=args.fixture_id,
        version_type=args.version_type,
    )

    print(
        f"Saved {rows_saved} {args.version_type} "
        f"strength-multiplier rows for {args.fixture_id}."
    )


if __name__ == "__main__":
    main()
