"""Rebuild and persist pre-match strength multipliers."""

from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.features.strength_multipliers import (
    rebuild_strength_multipliers,
)


def main() -> None:
    """Rebuild the strength-multiplier feature table."""
    with get_connection() as connection:
        rows_saved = rebuild_strength_multipliers(
            connection=connection,
        )

    print(f"Saved {rows_saved} strength-multiplier rows.")


if __name__ == "__main__":
    main()
