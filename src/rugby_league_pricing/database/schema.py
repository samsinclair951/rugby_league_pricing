from rugby_league_pricing.database.connection import get_connection


def initialise_database() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS teams (
                team_id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS team_source_mappings (
                team_source_mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                source_name TEXT NOT NULL,
                source_team_name TEXT NOT NULL,
                valid_from_season INTEGER,
                valid_to_season INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (team_id) REFERENCES teams(team_id),
                UNIQUE (
                    source_name,
                    source_team_name,
                    valid_from_season
                )
            );

            CREATE TABLE IF NOT EXISTS results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                fixture_id TEXT NOT NULL UNIQUE,
                season INTEGER NOT NULL,
                match_date TEXT NOT NULL,
                kick_off TEXT,
                home_team_id INTEGER NOT NULL,
                home_score INTEGER NOT NULL,
                away_team_id INTEGER NOT NULL,
                away_score INTEGER NOT NULL,
                referee TEXT,
                venue TEXT,
                attendance INTEGER,
                source_name TEXT NOT NULL,
                source_match_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id),
                FOREIGN KEY (home_team_id) REFERENCES teams(team_id),
                FOREIGN KEY (away_team_id) REFERENCES teams(team_id)
            );

            CREATE TABLE IF NOT EXISTS recent_form (
                recent_form_id INTEGER PRIMARY KEY AUTOINCREMENT,

                fixture_id TEXT NOT NULL,
                team_id INTEGER NOT NULL,
                opponent_id INTEGER NOT NULL,
                is_home INTEGER NOT NULL,

                match_date TEXT NOT NULL,
                season INTEGER NOT NULL,

                points_for INTEGER NOT NULL,
                points_against INTEGER NOT NULL,
                margin INTEGER NOT NULL,

                history_games_before INTEGER NOT NULL,

                recent_points_for_5 REAL,
                recent_points_against_5 REAL,
                recent_margin_5 REAL,
                recent_games_used_5 INTEGER NOT NULL,

                recent_points_for_10 REAL,
                recent_points_against_10 REAL,
                recent_margin_10 REAL,
                recent_games_used_10 INTEGER NOT NULL,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id),
                FOREIGN KEY (team_id) REFERENCES teams(team_id),
                FOREIGN KEY (opponent_id) REFERENCES teams(team_id),

                UNIQUE (
                    fixture_id,
                    team_id
                )
            );

            CREATE INDEX IF NOT EXISTS idx_recent_form_team_date
                ON recent_form(team_id, match_date);

            CREATE INDEX IF NOT EXISTS idx_recent_form_match_date
                ON recent_form(match_date);

            CREATE TABLE IF NOT EXISTS fixtures (
                fixture_id TEXT PRIMARY KEY,
                season INTEGER NOT NULL,
                match_date TEXT NOT NULL,
                kick_off TEXT,
                home_team_id INTEGER NOT NULL,
                away_team_id INTEGER NOT NULL,
                referee TEXT,
                venue TEXT,
                source_name TEXT NOT NULL,
                source_match_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (home_team_id) REFERENCES teams(team_id),
                FOREIGN KEY (away_team_id) REFERENCES teams(team_id)
            );

            CREATE INDEX IF NOT EXISTS idx_results_match_date
                ON results(match_date);

            CREATE INDEX IF NOT EXISTS idx_results_home_team
                ON results(home_team_id);

            CREATE INDEX IF NOT EXISTS idx_results_away_team
                ON results(away_team_id);

            CREATE INDEX IF NOT EXISTS idx_fixtures_match_date
                ON fixtures(match_date);

            CREATE INDEX IF NOT EXISTS idx_team_source_mappings_lookup
                ON team_source_mappings(
                    source_name,
                    source_team_name,
                    valid_from_season,
                    valid_to_season
                );
            """
        )


if __name__ == "__main__":
    initialise_database()
