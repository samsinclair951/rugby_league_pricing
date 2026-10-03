"""Rebuild and persist base player ratings from Patreon player files."""

from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.features.players import rebuild_player_ratings


def main() -> None:
    """Rebuild all base player-rating rows."""
    with get_connection() as connection:
        rows_saved = rebuild_player_ratings(connection=connection)

    print(f"Saved {rows_saved} player-rating rows.")


if __name__ == "__main__":
    main()
