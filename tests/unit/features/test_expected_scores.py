"""Tests for expected-score calculations."""

import pandas as pd
import pytest

from rugby_league_pricing.features.expected_scores import (
    calculate_expected_scores,
)


def test_calculates_expected_scores() -> None:
    """Expected scores should correctly combine all model features."""
    strength_multipliers = pd.DataFrame(
        [
            {
                "fixture_id": "2026-01-15_1_2",
                "home_attack_multiplier": 1.20,
                "home_defence_multiplier": 0.80,
                "away_attack_multiplier": 0.90,
                "away_defence_multiplier": 1.10,
            }
        ]
    )

    scoring_factors = pd.DataFrame(
        [
            {
                "fixture_id": "2026-01-15_1_2",
                "league_average_points": 20.0,
                "home_scoring_factor": 1.10,
                "away_scoring_factor": 0.90,
            }
        ]
    )

    expected_scores = calculate_expected_scores(
        strength_multipliers=strength_multipliers,
        scoring_factors=scoring_factors,
    )

    result = expected_scores.iloc[0]

    # Home: 20 × 1.20 × 1.10 × 1.10 = 29.04
    assert result["expected_home_points"] == pytest.approx(29.04)

    # Away: 20 × 0.90 × 0.80 × 0.90 = 12.96
    assert result["expected_away_points"] == pytest.approx(12.96)

    assert result["expected_margin"] == pytest.approx(16.08)
    assert result["expected_total_points"] == pytest.approx(42.0)


def test_average_teams_produce_league_average_scores() -> None:
    """Neutral multipliers should reproduce the league scoring averages."""
    strength_multipliers = pd.DataFrame(
        [
            {
                "fixture_id": "2026-01-15_1_2",
                "home_attack_multiplier": 1.0,
                "home_defence_multiplier": 1.0,
                "away_attack_multiplier": 1.0,
                "away_defence_multiplier": 1.0,
            }
        ]
    )

    scoring_factors = pd.DataFrame(
        [
            {
                "fixture_id": "2026-01-15_1_2",
                "league_average_points": 20.0,
                "home_scoring_factor": 1.10,
                "away_scoring_factor": 0.90,
            }
        ]
    )

    expected_scores = calculate_expected_scores(
        strength_multipliers,
        scoring_factors,
    )

    result = expected_scores.iloc[0]

    assert result["expected_home_points"] == pytest.approx(22.0)
    assert result["expected_away_points"] == pytest.approx(18.0)
    assert result["expected_margin"] == pytest.approx(4.0)
    assert result["expected_total_points"] == pytest.approx(40.0)


def test_rejects_missing_scoring_factors() -> None:
    """A fixture without matching scoring factors should fail clearly."""
    strength_multipliers = pd.DataFrame(
        [
            {
                "fixture_id": "2026-01-15_1_2",
                "home_attack_multiplier": 1.0,
                "home_defence_multiplier": 1.0,
                "away_attack_multiplier": 1.0,
                "away_defence_multiplier": 1.0,
            }
        ]
    )

    scoring_factors = pd.DataFrame(
        [
            {
                "fixture_id": "different_fixture",
                "league_average_points": 20.0,
                "home_scoring_factor": 1.1,
                "away_scoring_factor": 0.9,
            }
        ]
    )

    with pytest.raises(
        ValueError,
        match="Missing model features for fixtures",
    ):
        calculate_expected_scores(
            strength_multipliers,
            scoring_factors,
        )


def test_rejects_non_positive_model_features() -> None:
    """Multipliers and scoring factors must be greater than zero."""
    strength_multipliers = pd.DataFrame(
        [
            {
                "fixture_id": "2026-01-15_1_2",
                "home_attack_multiplier": 0.0,
                "home_defence_multiplier": 1.0,
                "away_attack_multiplier": 1.0,
                "away_defence_multiplier": 1.0,
            }
        ]
    )

    scoring_factors = pd.DataFrame(
        [
            {
                "fixture_id": "2026-01-15_1_2",
                "league_average_points": 20.0,
                "home_scoring_factor": 1.1,
                "away_scoring_factor": 0.9,
            }
        ]
    )

    with pytest.raises(
        ValueError,
        match="Model features must be greater than zero",
    ):
        calculate_expected_scores(
            strength_multipliers,
            scoring_factors,
        )
