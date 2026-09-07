"""Team-lineups feature package.

This package handles the manual input of expected or confirmed team lineups,
and converts them into player-adjusted strength multipliers.

Typical usage
-------------
From the dashboard or a script, load a lineup CSV and ingest it:

    from rugby_league_pricing.features.team_lineups import ingest_lineup_file
    from rugby_league_pricing.database.connection import get_connection

    with get_connection() as conn:
        lineup_rows, multiplier_rows = ingest_lineup_file(conn, "path/to/lineups.csv")
        print(f"Stored {lineup_rows} lineup rows and {multiplier_rows} multiplier rows.")
"""

from .build import (
    build_lineup_adjusted_multipliers,
    ingest_lineup_file,
    load_lineup_input,
)
from .upsert import upsert_expected_team_lineups

__all__ = [
    "build_lineup_adjusted_multipliers",
    "ingest_lineup_file",
    "load_lineup_input",
    "upsert_expected_team_lineups",
]
