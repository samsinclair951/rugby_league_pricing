"""Shared constants for recent-form feature modules."""

RESULTS_SOURCE = "rugby_league_project"
DEFAULT_WINDOWS = (5, 10)

RESULTS_QUERY = """
    SELECT
        fixture_id,
        season,
        match_date,
        home_team_id,
        home_score,
        away_team_id,
        away_score
    FROM results
    WHERE source_name = ?
      AND home_score IS NOT NULL
      AND away_score IS NOT NULL
    ORDER BY
        match_date,
        fixture_id
"""
