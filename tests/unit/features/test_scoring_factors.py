"""Tests for historical scoring-factor calculations."""

import pandas as pd
import pytest

from rugby_league_pricing.features.scoring_factors import (
    calculate_historical_scoring_factors,
)


def test_calculates_scoring_factors_using_previous_dates_only() -> None:
    """Factors should use completed matches from earlier dates only."""
    results = pd.DataFrame(
        [
            {
                "fixture_id": "2026-01-01_1_2",
                "match_date": "2026-01-01",
                "home_points": 30,
                "away_points": 10,
            },
            {
                "fixture_id": "2026-01-08_3_4",
                "match_date": "2026-01-08",
                "home_points": 20,
                "away_points": 20,
            },
            {
                "fixture_id": "2026-01-15_1_3",
                "match_date": "2026-01-15",
                "home_points": 40,
                "away_points": 10,
            },
        ]
    )

    factors = calculate_historical_scoring_factors(results)

    first_fixture = factors.loc[factors["fixture_id"] == "2026-01-01_1_2"].iloc[0]

    second_fixture = factors.loc[factors["fixture_id"] == "2026-01-08_3_4"].iloc[0]

    third_fixture = factors.loc[factors["fixture_id"] == "2026-01-15_1_3"].iloc[0]

    assert pd.isna(first_fixture["league_average_points"])
    assert pd.isna(first_fixture["home_scoring_factor"])
    assert pd.isna(first_fixture["away_scoring_factor"])

    # After the first result:
    # league average = (30 + 10) / 2 = 20
    # home factor = 30 / 20 = 1.5
    # away factor = 10 / 20 = 0.5
    assert second_fixture["league_average_points"] == pytest.approx(20.0)
    assert second_fixture["home_scoring_factor"] == pytest.approx(1.5)
    assert second_fixture["away_scoring_factor"] == pytest.approx(0.5)

    # After the first two results:
    # total points = 30 + 10 + 20 + 20 = 80
    # league average per team = 80 / 4 = 20
    # average home points = 50 / 2 = 25
    # average away points = 30 / 2 = 15
    assert third_fixture["league_average_points"] == pytest.approx(20.0)
    assert third_fixture["home_scoring_factor"] == pytest.approx(1.25)
    assert third_fixture["away_scoring_factor"] == pytest.approx(0.75)


def test_same_date_fixtures_receive_identical_pre_match_factors() -> None:
    """Fixtures on the same date must not influence each other."""
    results = pd.DataFrame(
        [
            {
                "fixture_id": "2026-01-01_1_2",
                "match_date": "2026-01-01",
                "home_points": 30,
                "away_points": 10,
            },
            {
                "fixture_id": "2026-01-08_3_4",
                "match_date": "2026-01-08",
                "home_points": 50,
                "away_points": 0,
            },
            {
                "fixture_id": "2026-01-08_5_6",
                "match_date": "2026-01-08",
                "home_points": 10,
                "away_points": 40,
            },
        ]
    )

    factors = calculate_historical_scoring_factors(results)

    same_date_factors = factors[
        factors["fixture_id"].isin(
            [
                "2026-01-08_3_4",
                "2026-01-08_5_6",
            ]
        )
    ]

    assert same_date_factors["league_average_points"].nunique() == 1
    assert same_date_factors["home_scoring_factor"].nunique() == 1
    assert same_date_factors["away_scoring_factor"].nunique() == 1

    assert same_date_factors["league_average_points"].iloc[0] == pytest.approx(20.0)
    assert same_date_factors["home_scoring_factor"].iloc[0] == pytest.approx(1.5)
    assert same_date_factors["away_scoring_factor"].iloc[0] == pytest.approx(0.5)


def test_rejects_missing_required_columns() -> None:
    """Missing input columns should produce a useful error."""
    results = pd.DataFrame(
        [
            {
                "fixture_id": "2026-01-01_1_2",
                "match_date": "2026-01-01",
            }
        ]
    )

    with pytest.raises(
        ValueError,
        match="Results are missing required columns",
    ):
        calculate_historical_scoring_factors(results)


def test_rejects_duplicate_fixture_ids() -> None:
    """Each completed fixture must appear only once."""
    results = pd.DataFrame(
        [
            {
                "fixture_id": "duplicate",
                "match_date": "2026-01-01",
                "home_points": 20,
                "away_points": 10,
            },
            {
                "fixture_id": "duplicate",
                "match_date": "2026-01-08",
                "home_points": 30,
                "away_points": 12,
            },
        ]
    )

    with pytest.raises(
        ValueError,
        match="duplicate fixture IDs",
    ):
        calculate_historical_scoring_factors(results)
