from __future__ import annotations

from math import lgamma

import numpy as np

from .base import ScoreMatrix, build_score_grid


def poisson_probabilities(
    expected_score: float,
    scores: np.ndarray,
) -> np.ndarray:
    """Calculate a truncated and renormalised Poisson distribution."""
    if expected_score < 0:
        raise ValueError("expected_score cannot be negative.")

    if expected_score == 0:
        probabilities = np.zeros(len(scores), dtype=float)
        probabilities[0] = 1.0
        return probabilities

    log_probabilities = (
        -expected_score
        + scores * np.log(expected_score)
        - np.array([lgamma(int(score) + 1) for score in scores])
    )

    probabilities = np.exp(log_probabilities)
    total_probability = probabilities.sum()

    if total_probability <= 0:
        raise ValueError("Poisson probabilities could not be normalised.")

    return probabilities / total_probability


def build_poisson_score_matrix(
    expected_home_score: float,
    expected_away_score: float,
    max_score: int = 100,
) -> ScoreMatrix:
    """Build an independent Poisson home-away score matrix."""
    scores = build_score_grid(max_score=max_score)

    home_probabilities = poisson_probabilities(
        expected_score=expected_home_score,
        scores=scores,
    )
    away_probabilities = poisson_probabilities(
        expected_score=expected_away_score,
        scores=scores,
    )

    probabilities = np.outer(home_probabilities, away_probabilities)
    probabilities /= probabilities.sum()

    return ScoreMatrix(
        probabilities=probabilities,
        scores=scores,
    )
