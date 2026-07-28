from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.features.expected_scores import (
    rebuild_expected_scores,
)


def main() -> None:
    """Rebuild and persist expected scores."""
    with get_connection() as connection:
        rows_saved = rebuild_expected_scores(
            connection=connection,
        )

    print(f"Saved {rows_saved} expected-score rows.")


if __name__ == "__main__":
    main()
