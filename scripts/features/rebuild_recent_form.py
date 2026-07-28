from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.features.recent_form import rebuild_recent_form


def main() -> None:
    with get_connection() as connection:
        rows_upserted = rebuild_recent_form(
            connection=connection,
        )

        connection.commit()

    print(f"Saved {rows_upserted} recent-form rows.")


if __name__ == "__main__":
    main()
