from rugby_league_pricing.database.connection import get_connection


def initialise_database() -> None:
    """Create all database tables and indexes."""
    with get_connection() as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS tournaments (
                tournament_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_name TEXT NOT NULL,
                country TEXT NOT NULL,
                competition_type TEXT,
                active INTEGER NOT NULL DEFAULT 1
                    CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                UNIQUE (
                    tournament_name,
                    country
                )
            );

            CREATE TABLE IF NOT EXISTS tournament_source_mappings (
                tournament_source_mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER NOT NULL,
                source_name TEXT NOT NULL,
                source_tournament_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (tournament_id)
                    REFERENCES tournaments(tournament_id),

                UNIQUE (
                    source_name,
                    source_tournament_name
                )
            );

            CREATE TABLE IF NOT EXISTS competition_stages (
                competition_stage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER NOT NULL,
                stage_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (tournament_id)
                    REFERENCES tournaments(tournament_id),

                UNIQUE (
                    tournament_id,
                    stage_name
                )
            );

            CREATE TABLE IF NOT EXISTS teams (
                team_id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT NOT NULL UNIQUE,
                current_tournament_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (current_tournament_id)
                    REFERENCES tournaments(tournament_id)
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

                FOREIGN KEY (team_id)
                    REFERENCES teams(team_id),

                UNIQUE (
                    source_name,
                    source_team_name,
                    valid_from_season
                )
            );

            CREATE TABLE IF NOT EXISTS fixtures (
                fixture_id TEXT PRIMARY KEY,
                season INTEGER NOT NULL,
                tournament_id INTEGER NOT NULL,
                competition_stage_id INTEGER,
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

                FOREIGN KEY (tournament_id)
                    REFERENCES tournaments(tournament_id),

                FOREIGN KEY (competition_stage_id)
                    REFERENCES competition_stages(competition_stage_id),

                FOREIGN KEY (home_team_id)
                    REFERENCES teams(team_id),

                FOREIGN KEY (away_team_id)
                    REFERENCES teams(team_id)
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

                FOREIGN KEY (fixture_id)
                    REFERENCES fixtures(fixture_id),

                FOREIGN KEY (home_team_id)
                    REFERENCES teams(team_id),

                FOREIGN KEY (away_team_id)
                    REFERENCES teams(team_id)
            );

            CREATE TABLE IF NOT EXISTS players (
                player_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                season INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                primary_position TEXT,
                active INTEGER NOT NULL DEFAULT 1
                    CHECK (active IN (0, 1)),
                source_name TEXT NOT NULL,
                source_player_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (
                    player_id,
                    season,
                    team_id
                ),

                FOREIGN KEY (team_id)
                    REFERENCES teams(team_id)
            );

            CREATE TABLE IF NOT EXISTS teamsheets (
                fixture_id TEXT NOT NULL,
                season INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                player_id TEXT NOT NULL,
                side TEXT NOT NULL
                    CHECK (side IN ('home', 'away')),
                position TEXT,
                lineup_order INTEGER NOT NULL
                    CHECK (lineup_order BETWEEN 1 AND 17),
                is_starting INTEGER NOT NULL
                    CHECK (is_starting IN (0, 1)),
                source_name TEXT NOT NULL,
                source_match_id TEXT,
                source_url TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (
                    fixture_id,
                    team_id,
                    player_id
                ),

                FOREIGN KEY (fixture_id)
                    REFERENCES fixtures(fixture_id),

                FOREIGN KEY (team_id)
                    REFERENCES teams(team_id),

                FOREIGN KEY (
                    player_id,
                    season,
                    team_id
                )
                    REFERENCES players(
                        player_id,
                        season,
                        team_id
                    )
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

                FOREIGN KEY (fixture_id)
                    REFERENCES fixtures(fixture_id),

                FOREIGN KEY (team_id)
                    REFERENCES teams(team_id),

                FOREIGN KEY (opponent_id)
                    REFERENCES teams(team_id),

                UNIQUE (
                    fixture_id,
                    team_id
                )
            );

            CREATE TABLE IF NOT EXISTS strength_multipliers (
                strength_multiplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
                fixture_id TEXT NOT NULL,
                team_id INTEGER NOT NULL,
                opponent_id INTEGER NOT NULL,
                is_home INTEGER NOT NULL,
                match_date TEXT NOT NULL,
                season INTEGER NOT NULL,
                league_average_points REAL,
                raw_attack_multiplier REAL,
                raw_defence_multiplier REAL,
                attack_multiplier REAL,
                defence_multiplier REAL,
                scaled_attack_multiplier REAL,
                scaled_defence_multiplier REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (fixture_id)
                    REFERENCES fixtures(fixture_id),

                FOREIGN KEY (team_id)
                    REFERENCES teams(team_id),

                FOREIGN KEY (opponent_id)
                    REFERENCES teams(team_id),

                UNIQUE (
                    fixture_id,
                    team_id
                )
            );

            CREATE TABLE IF NOT EXISTS expected_scores (
                expected_score_id INTEGER PRIMARY KEY AUTOINCREMENT,
                fixture_id TEXT NOT NULL UNIQUE,
                match_date TEXT NOT NULL,
                season INTEGER NOT NULL,
                home_team_id INTEGER NOT NULL,
                away_team_id INTEGER NOT NULL,
                league_average_points REAL NOT NULL,
                home_scoring_factor REAL NOT NULL,
                away_scoring_factor REAL NOT NULL,
                home_attack_multiplier REAL NOT NULL,
                home_defence_multiplier REAL NOT NULL,
                away_attack_multiplier REAL NOT NULL,
                away_defence_multiplier REAL NOT NULL,
                expected_home_score REAL NOT NULL,
                expected_away_score REAL NOT NULL,
                expected_margin REAL NOT NULL,
                expected_total REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (fixture_id)
                    REFERENCES fixtures(fixture_id),

                FOREIGN KEY (home_team_id)
                    REFERENCES teams(team_id),

                FOREIGN KEY (away_team_id)
                    REFERENCES teams(team_id)
            );

            CREATE TABLE IF NOT EXISTS expected_score_predictions (
                expected_score_prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,

                fixture_id TEXT NOT NULL UNIQUE,
                prediction_date TEXT NOT NULL,

                home_team_id INTEGER NOT NULL,
                away_team_id INTEGER NOT NULL,

                league_average_points REAL NOT NULL,
                home_scoring_factor REAL NOT NULL,
                away_scoring_factor REAL NOT NULL,

                home_attack_multiplier REAL NOT NULL,
                home_defence_multiplier REAL NOT NULL,
                away_attack_multiplier REAL NOT NULL,
                away_defence_multiplier REAL NOT NULL,

                expected_home_score REAL NOT NULL,
                expected_away_score REAL NOT NULL,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (fixture_id)
                    REFERENCES fixtures(fixture_id),

                FOREIGN KEY (home_team_id)
                    REFERENCES teams(team_id),

                FOREIGN KEY (away_team_id)
                    REFERENCES teams(team_id)
            );

            CREATE TABLE IF NOT EXISTS historical_score_matrices (
                matrix_version TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                max_score INTEGER NOT NULL,
                weight_config TEXT NOT NULL,
                probability_matrix BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (
                    matrix_version,
                    as_of_date
                )
            );

            CREATE INDEX IF NOT EXISTS idx_tournaments_country
                ON tournaments(country);

            CREATE INDEX IF NOT EXISTS idx_tournament_source_mappings_lookup
                ON tournament_source_mappings(
                    source_name,
                    source_tournament_name
                );

            CREATE INDEX IF NOT EXISTS idx_competition_stages_tournament
                ON competition_stages(
                    tournament_id,
                    stage_name
                );

            CREATE INDEX IF NOT EXISTS idx_teams_current_tournament
                ON teams(current_tournament_id);

            CREATE INDEX IF NOT EXISTS idx_team_source_mappings_lookup
                ON team_source_mappings(
                    source_name,
                    source_team_name,
                    valid_from_season,
                    valid_to_season
                );

            CREATE INDEX IF NOT EXISTS idx_fixtures_match_date
                ON fixtures(match_date);

            CREATE INDEX IF NOT EXISTS idx_fixtures_tournament_season
                ON fixtures(
                    tournament_id,
                    season
                );

            CREATE INDEX IF NOT EXISTS idx_fixtures_stage
                ON fixtures(competition_stage_id);

            CREATE INDEX IF NOT EXISTS idx_results_match_date
                ON results(match_date);

            CREATE INDEX IF NOT EXISTS idx_results_home_team
                ON results(home_team_id);

            CREATE INDEX IF NOT EXISTS idx_results_away_team
                ON results(away_team_id);

            CREATE INDEX IF NOT EXISTS idx_players_season_team
                ON players(
                    season,
                    team_id
                );

            CREATE INDEX IF NOT EXISTS idx_players_source_player
                ON players(
                    source_name,
                    source_player_id
                );

            CREATE INDEX IF NOT EXISTS idx_teamsheets_fixture
                ON teamsheets(fixture_id);

            CREATE INDEX IF NOT EXISTS idx_teamsheets_player
                ON teamsheets(
                    player_id,
                    season
                );

            CREATE INDEX IF NOT EXISTS idx_teamsheets_team_season
                ON teamsheets(
                    team_id,
                    season
                );

            CREATE INDEX IF NOT EXISTS idx_recent_form_team_date
                ON recent_form(
                    team_id,
                    match_date
                );

            CREATE INDEX IF NOT EXISTS idx_recent_form_match_date
                ON recent_form(match_date);

            CREATE INDEX IF NOT EXISTS idx_strength_multipliers_team_date
                ON strength_multipliers(
                    team_id,
                    match_date
                );

            CREATE INDEX IF NOT EXISTS idx_strength_multipliers_fixture
                ON strength_multipliers(fixture_id);

            CREATE INDEX IF NOT EXISTS idx_expected_scores_match_date
                ON expected_scores(match_date);

            CREATE INDEX IF NOT EXISTS idx_expected_scores_home_team
                ON expected_scores(home_team_id);

            CREATE INDEX IF NOT EXISTS idx_expected_scores_away_team
                ON expected_scores(away_team_id);

            CREATE INDEX IF NOT EXISTS idx_historical_score_matrices_as_of_date
                ON historical_score_matrices(as_of_date);
            """
        )


if __name__ == "__main__":
    initialise_database()
