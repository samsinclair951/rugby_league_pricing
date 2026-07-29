"""Tests for expected-score calculations."""

import sqlite3

import pandas as pd
import pytest

from rugby_league_pricing.features.expected_scores import upsert_expected_scores
from rugby_league_pricing.features.expected_scores.core import (
    _validate_model_features,
)


def test_validate_model_features_rejects_missing_or_non_positive_values() -> None:
    """Model-feature validation should catch missing or non-positive inputs."""
    expected_scores = pd.DataFrame(
        {
            "fixture_id": ["fixture_1"],
            "league_average_points": [10.0],
            "home_scoring_factor": [1.0],
            "away_scoring_factor": [1.0],
            "home_attack_multiplier": [1.0],
            "home_defence_multiplier": [1.0],
            "away_attack_multiplier": [1.0],
            "away_defence_multiplier": [0.0],
        }
    )

    with pytest.raises(ValueError, match="greater than zero"):
        _validate_model_features(
            expected_scores=expected_scores,
            model_feature_columns=[
                "home_attack_multiplier",
                "home_defence_multiplier",
                "away_attack_multiplier",
                "away_defence_multiplier",
                "league_average_points",
                "home_scoring_factor",
                "away_scoring_factor",
            ],
        )


def test_upsert_expected_scores_round_trip() -> None:
    """Expected scores should be saved to SQLite correctly."""
    connection = sqlite3.connect(":memory:")

    try:
        connection.execute(
            """
            CREATE TABLE expected_scores (
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
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        expected_scores = pd.DataFrame(
            {
                "fixture_id": ["fixture_1"],
                "match_date": [pd.Timestamp("2026-01-01")],
                "season": [2026],
                "home_team_id": [1],
                "away_team_id": [2],
                "league_average_points": [24.0],
                "home_scoring_factor": [1.1],
                "away_scoring_factor": [0.9],
                "home_attack_multiplier": [1.2],
                "home_defence_multiplier": [0.95],
                "away_attack_multiplier": [0.85],
                "away_defence_multiplier": [1.1],
                "expected_home_score": [34.85],
                "expected_away_score": [17.44],
                "expected_margin": [17.41],
                "expected_total": [52.29],
            }
        )

        rows_saved = upsert_expected_scores(
            connection=connection,
            expected_scores=expected_scores,
        )

        assert rows_saved == 1

        row = connection.execute(
            """
            SELECT
                fixture_id,
                match_date,
                season,
                home_team_id,
                away_team_id,
                league_average_points,
                home_scoring_factor,
                away_scoring_factor,
                home_attack_multiplier,
                home_defence_multiplier,
                away_attack_multiplier,
                away_defence_multiplier,
                expected_home_score,
                expected_away_score,
                expected_margin,
                expected_total
            FROM expected_scores
            """
        ).fetchone()

        assert row == (
            "fixture_1",
            "2026-01-01",
            2026,
            1,
            2,
            24.0,
            1.1,
            0.9,
            1.2,
            0.95,
            0.85,
            1.1,
            34.85,
            17.44,
            17.41,
            52.29,
        )

    finally:
        connection.close()
