import numpy as np
import pytest

from rugby_league_pricing.pricing.score_matrices.poisson import (
    build_poisson_score_matrix,
    poisson_probabilities,
)


def test_poisson_probabilities_sum_to_one() -> None:
    scores = np.arange(101)

    probabilities = poisson_probabilities(
        expected_score=24.0,
        scores=scores,
    )

    assert probabilities.shape == (101,)
    assert probabilities.sum() == pytest.approx(1.0)
    assert np.all(probabilities >= 0)


def test_poisson_probabilities_have_expected_mean() -> None:
    scores = np.arange(101)

    probabilities = poisson_probabilities(
        expected_score=24.0,
        scores=scores,
    )

    implied_mean = float(np.dot(scores, probabilities))

    assert implied_mean == pytest.approx(24.0, abs=1e-6)


def test_poisson_probabilities_support_zero_expected_score() -> None:
    scores = np.arange(11)

    probabilities = poisson_probabilities(
        expected_score=0.0,
        scores=scores,
    )

    assert probabilities[0] == pytest.approx(1.0)
    assert probabilities[1:].sum() == pytest.approx(0.0)


def test_poisson_probabilities_reject_negative_expected_score() -> None:
    scores = np.arange(11)

    with pytest.raises(
        ValueError,
        match="expected_score cannot be negative",
    ):
        poisson_probabilities(
            expected_score=-1.0,
            scores=scores,
        )


def test_build_poisson_score_matrix() -> None:
    matrix = build_poisson_score_matrix(
        expected_home_score=26.0,
        expected_away_score=18.0,
        max_score=100,
    )

    assert matrix.probabilities.shape == (101, 101)
    assert matrix.probabilities.sum() == pytest.approx(1.0)
    assert np.all(matrix.probabilities >= 0)

    assert matrix.expected_home_score == pytest.approx(26.0, abs=1e-6)
    assert matrix.expected_away_score == pytest.approx(18.0, abs=1e-6)


def test_swapping_expected_scores_transposes_matrix() -> None:
    original = build_poisson_score_matrix(
        expected_home_score=26.0,
        expected_away_score=18.0,
    )

    swapped = build_poisson_score_matrix(
        expected_home_score=18.0,
        expected_away_score=26.0,
    )

    assert swapped.probabilities == pytest.approx(
        original.probabilities.T
    )


def test_poisson_matrix_probability_equals_product_of_marginals() -> None:
    matrix = build_poisson_score_matrix(
        expected_home_score=20.0,
        expected_away_score=14.0,
        max_score=100,
    )

    home_probabilities = matrix.probabilities.sum(axis=1)
    away_probabilities = matrix.probabilities.sum(axis=0)

    assert matrix.probabilities[20, 14] == pytest.approx(
        home_probabilities[20] * away_probabilities[14]
    )