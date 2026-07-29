REQUIRED_STRENGTH_COLUMNS = {
    "fixture_id",
    "home_attack_multiplier",
    "home_defence_multiplier",
    "away_attack_multiplier",
    "away_defence_multiplier",
}

REQUIRED_SCORING_FACTOR_COLUMNS = {
    "fixture_id",
    "league_average_points",
    "home_scoring_factor",
    "away_scoring_factor",
}

EXPECTED_SCORE_COLUMNS = [
    "fixture_id",
    "expected_home_points",
    "expected_away_points",
    "expected_margin",
    "expected_total_points",
]

MODEL_FEATURE_COLUMNS = [
    "home_attack_multiplier",
    "home_defence_multiplier",
    "away_attack_multiplier",
    "away_defence_multiplier",
    "league_average_points",
    "home_scoring_factor",
    "away_scoring_factor",
]

EXPECTED_SCORES_UPSERT_COLUMNS = [
    "fixture_id",
    "match_date",
    "season",
    "home_team_id",
    "away_team_id",
    "league_average_points",
    "home_scoring_factor",
    "away_scoring_factor",
    "home_attack_multiplier",
    "home_defence_multiplier",
    "away_attack_multiplier",
    "away_defence_multiplier",
    "expected_home_score",
    "expected_away_score",
    "expected_margin",
    "expected_total",
]
