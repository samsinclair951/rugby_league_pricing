"""Rebuild expected-score predictions for future fixtures."""

from rugby_league_pricing.database.connection import (
    get_connection,
)
from rugby_league_pricing.features.expected_scores.predict import (
    rebuild_expected_score_predictions,
)


def main() -> None:
    """Rebuild and persist future expected-score predictions."""
    with get_connection() as connection:
        rows_saved = rebuild_expected_score_predictions(
            connection=connection,
        )

    print(f"Saved {rows_saved} expected-score prediction rows.")


if __name__ == "__main__":
    main()
