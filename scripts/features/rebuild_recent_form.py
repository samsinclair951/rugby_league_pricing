import argparse

from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.features.recent_form import rebuild_recent_form



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-name",
        type=str,
        default="rugby_league_project",
        choices=[
            "rugby_league_project",
            "patreon",
        ],
    )
    args = parser.parse_args()

    with get_connection() as connection:
        rows_upserted = rebuild_recent_form(
            connection=connection,
            source_name=args.source_name,
        )

        connection.commit()

    print(f"Saved {rows_upserted} recent-form rows.")


if __name__ == "__main__":
    main()
