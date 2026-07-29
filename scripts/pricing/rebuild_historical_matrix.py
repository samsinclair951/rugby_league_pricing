from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.pricing.score_matrices.historical import (
    upsert_matrix,
)


def main() -> None:
    """Rebuild and persist the historical score matrix."""
    with get_connection() as connection:
        rows_saved = upsert_matrix(
            connection=connection,
        )

    print(f"Saved {rows_saved} historical score-matrix rows.")


if __name__ == "__main__":
    main()