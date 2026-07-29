import numpy as np
import pandas as pd
import pytest

from rugby_league_pricing.pricing import (
    blend_score_matrices,
    build_blended_score_matrix,
    build_poisson_score_matrix,
    build_shifted_historical_score_matrix,
)


@pytest.fixture
def historical_results() -> pd.DataFrame:
    """Return a small historical rugby league results sample."""
    return pd.DataFrame(
        {
            "home_score": [20, 24, 30, 12, 36, 18],
            "away_score": [10, 20, 18, 24, 16, 14],
        }
    )


def test_poisson_score_matrix_sums_to_one() -> None:
    matrix = build_poisson_score_matrix(
        expected_home_score=28.0,
        expected_away_score=18.0,
    )

    assert matrix.probabilities.sum() == pytest.approx(1.0)


def test_poisson_matrix_preserves_expected_scores() -> None:
    matrix = build_poisson_score_matrix(
        expected_home_score=28.0,
        expected_away_score=18.0,
        max_score=100,
    )

    assert matrix.expected_home_score == pytest.approx(28.0, abs=1e-6)
    assert matrix.expected_away_score == pytest.approx(18.0, abs=1e-6)


def test_poisson_matrix_has_expected_shape() -> None:
    matrix = build_poisson_score_matrix(
        expected_home_score=24.0,
        expected_away_score=20.0,
        max_score=60,
    )

    assert matrix.probabilities.shape == (61, 61)
    assert len(matrix.scores) == 61


def test_shifted_historical_matrix_sums_to_one(
    historical_results: pd.DataFrame,
) -> None:
    matrix = build_shifted_historical_score_matrix(
        historical_results=historical_results,
        expected_home_score=30.0,
        expected_away_score=16.0,
    )

    assert matrix.probabilities.sum() == pytest.approx(1.0)


def test_full_scaling_matches_target_means(
    historical_results: pd.DataFrame,
) -> None:
    matrix = build_shifted_historical_score_matrix(
        historical_results=historical_results,
        expected_home_score=30.0,
        expected_away_score=16.0,
        max_score=100,
        scale_strength=1.0,
    )

    assert matrix.expected_home_score == pytest.approx(30.0)
    assert matrix.expected_away_score == pytest.approx(16.0)


def test_zero_scale_strength_preserves_historical_means(
    historical_results: pd.DataFrame,
) -> None:
    matrix = build_shifted_historical_score_matrix(
        historical_results=historical_results,
        expected_home_score=30.0,
        expected_away_score=16.0,
        max_score=100,
        scale_strength=0.0,
    )

    assert matrix.expected_home_score == pytest.approx(
        historical_results["home_score"].mean()
    )
    assert matrix.expected_away_score == pytest.approx(
        historical_results["away_score"].mean()
    )


def test_blend_sums_to_one(
    historical_results: pd.DataFrame,
) -> None:
    poisson_matrix = build_poisson_score_matrix(
        expected_home_score=30.0,
        expected_away_score=16.0,
    )
    historical_matrix = build_shifted_historical_score_matrix(
        historical_results=historical_results,
        expected_home_score=30.0,
        expected_away_score=16.0,
    )

    blended = blend_score_matrices(
        poisson_matrix=poisson_matrix,
        historical_matrix=historical_matrix,
        historical_weight=0.20,
    )

    assert blended.probabilities.sum() == pytest.approx(1.0)


def test_zero_historical_weight_returns_poisson_matrix(
    historical_results: pd.DataFrame,
) -> None:
    poisson_matrix = build_poisson_score_matrix(
        expected_home_score=30.0,
        expected_away_score=16.0,
    )
    historical_matrix = build_shifted_historical_score_matrix(
        historical_results=historical_results,
        expected_home_score=30.0,
        expected_away_score=16.0,
    )

    blended = blend_score_matrices(
        poisson_matrix=poisson_matrix,
        historical_matrix=historical_matrix,
        historical_weight=0.0,
    )

    np.testing.assert_allclose(
        blended.probabilities,
        poisson_matrix.probabilities,
    )


def test_complete_blended_matrix_builds(
    historical_results: pd.DataFrame,
) -> None:
    matrix = build_blended_score_matrix(
        historical_results=historical_results,
        expected_home_score=30.0,
        expected_away_score=16.0,
        historical_weight=0.20,
        scale_strength=1.0,
    )

    assert matrix.probabilities.sum() == pytest.approx(1.0)
    assert matrix.expected_home_score == pytest.approx(30.0)
    assert matrix.expected_away_score == pytest.approx(16.0)


@pytest.mark.parametrize(
    ("historical_weight", "expected_message"),
    [
        (-0.1, "historical_weight"),
        (1.1, "historical_weight"),
    ],
)
def test_invalid_historical_weight_raises(
    historical_results: pd.DataFrame,
    historical_weight: float,
    expected_message: str,
) -> None:
    poisson_matrix = build_poisson_score_matrix(30.0, 16.0)
    historical_matrix = build_shifted_historical_score_matrix(
        historical_results,
        30.0,
        16.0,
    )

    with pytest.raises(ValueError, match=expected_message):
        blend_score_matrices(
            poisson_matrix,
            historical_matrix,
            historical_weight=historical_weight,
        )