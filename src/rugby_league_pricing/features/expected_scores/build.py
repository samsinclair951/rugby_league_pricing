"""Build and rebuild expected-score data from database inputs."""

from __future__ import annotations

import sqlite3

import pandas as pd

from rugby_league_pricing.features.scoring_factors import (
    calculate_historical_scoring_factors,
)

from .core import calculate_expected_scores
from .upsert import upsert_expected_scores


def _load_strength_multipliers(connection: sqlite3.Connection) -> pd.DataFrame:
    """Load pre-match strength multipliers from the database."""
    return pd.read_sql_query(
        """
        SELECT
            fixture_id,
            match_date,
            season,
            team_id,
            is_home,
            scaled_attack_multiplier AS attack_multiplier,
            scaled_defence_multiplier AS defence_multiplier
        FROM strength_multipliers
        ORDER BY match_date, fixture_id, is_home DESC
        """,
        connection,
        parse_dates=["match_date"],
    )


def _build_strength_features(strength_multipliers: pd.DataFrame) -> pd.DataFrame:
    """Pivot home and away strength rows into one row per fixture."""
    home_strength = strength_multipliers.loc[
        strength_multipliers["is_home"] == 1
    ].rename(
        columns={
            "team_id": "home_team_id",
            "attack_multiplier": "home_attack_multiplier",
            "defence_multiplier": "home_defence_multiplier",
        }
    )[
        [
            "fixture_id",
            "match_date",
            "season",
            "home_team_id",
            "home_attack_multiplier",
            "home_defence_multiplier",
        ]
    ]

    away_strength = strength_multipliers.loc[
        strength_multipliers["is_home"] == 0
    ].rename(
        columns={
            "team_id": "away_team_id",
            "attack_multiplier": "away_attack_multiplier",
            "defence_multiplier": "away_defence_multiplier",
        }
    )[
        [
            "fixture_id",
            "away_team_id",
            "away_attack_multiplier",
            "away_defence_multiplier",
        ]
    ]

    return home_strength.merge(
        away_strength,
        on="fixture_id",
        how="inner",
        validate="one_to_one",
    )


def _load_results(connection: sqlite3.Connection) -> pd.DataFrame:
    """Load completed results from the database."""
    return pd.read_sql_query(
        """
        SELECT
            fixture_id,
            match_date,
            home_score AS home_points,
            away_score AS away_points
        FROM results
        ORDER BY match_date, fixture_id
        """,
        connection,
        parse_dates=["match_date"],
    )


def _prepare_scoring_factors(results: pd.DataFrame) -> pd.DataFrame:
    """Calculate scoring factors from historical results."""
    scoring_factors = calculate_historical_scoring_factors(results=results)

    return scoring_factors.dropna(
        subset=[
            "league_average_points",
            "home_scoring_factor",
            "away_scoring_factor",
        ]
    )


def _filter_strength_features(
    strength_features: pd.DataFrame,
    scoring_factors: pd.DataFrame,
) -> pd.DataFrame:
    """Keep only fixtures that have scoring factors available."""
    return strength_features[
        strength_features["fixture_id"].isin(scoring_factors["fixture_id"])
    ].copy()


def _assemble_expected_scores(
    strength_features: pd.DataFrame,
    scoring_factors: pd.DataFrame,
    calculated_scores: pd.DataFrame,
) -> pd.DataFrame:
    """Combine strength, scoring-factor and expected-score outputs."""
    return (
        strength_features.merge(
            scoring_factors,
            on="fixture_id",
            how="inner",
            validate="one_to_one",
        )
        .merge(
            calculated_scores,
            on="fixture_id",
            how="inner",
            validate="one_to_one",
        )
        .rename(
            columns={
                "expected_home_points": "expected_home_score",
                "expected_away_points": "expected_away_score",
                "expected_total_points": "expected_total",
            }
        )
    )


def build_expected_scores(connection: sqlite3.Connection) -> pd.DataFrame:
    """Build database-ready expected scores for completed fixtures."""
    strength_multipliers = _load_strength_multipliers(connection=connection)
    strength_features = _build_strength_features(strength_multipliers)

    results = _load_results(connection=connection)
    scoring_factors = _prepare_scoring_factors(results=results)
    strength_features = _filter_strength_features(
        strength_features=strength_features,
        scoring_factors=scoring_factors,
    )

    calculated_scores = calculate_expected_scores(
        strength_multipliers=strength_features,
        scoring_factors=scoring_factors,
    )

    return _assemble_expected_scores(
        strength_features=strength_features,
        scoring_factors=scoring_factors,
        calculated_scores=calculated_scores,
    )


def rebuild_expected_scores(connection: sqlite3.Connection) -> int:
    """Build and persist expected scores."""
    expected_scores = build_expected_scores(connection=connection)

    return upsert_expected_scores(
        connection=connection,
        expected_scores=expected_scores,
    )
