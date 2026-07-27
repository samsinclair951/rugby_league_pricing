from rugby_league_pricing.database.connection import get_connection


def initialise_database() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS fixtures (
                fixture_id INTEGER PRIMARY KEY AUTOINCREMENT,
                competition TEXT NOT NULL,
                season INTEGER NOT NULL,
                round TEXT,
                match_date TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                home_score INTEGER,
                away_score INTEGER,
                venue TEXT,
                status TEXT NOT NULL DEFAULT 'scheduled',
                UNIQUE(match_date, home_team, away_team)
            )
            """
        )


if __name__ == "__main__":
    initialise_database()
    print("Database schema initialised.")