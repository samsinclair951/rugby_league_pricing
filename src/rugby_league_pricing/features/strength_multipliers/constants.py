"""Shared constants for strength-multiplier feature modules."""

DEFAULT_FORM_WINDOW = 5
DEFAULT_LEAGUE_WINDOW = 50
DEFAULT_PRIOR_GAMES = 3
DEFAULT_ITERATIONS = 10

RECENT_FORM_QUERY = """
    SELECT
        fixture_id,
        team_id,
        opponent_id,
        is_home,
        match_date,
        season,
        points_for,
        points_against,
        history_games_before,
        recent_points_for_5,
        recent_points_against_5,
        recent_games_used_5,
        recent_points_for_10,
        recent_points_against_10,
        recent_games_used_10
    FROM recent_form
    ORDER BY
        match_date,
        fixture_id,
        team_id
"""
