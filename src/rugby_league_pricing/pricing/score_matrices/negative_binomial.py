from __future__ import annotations

import numpy as np
from scipy.stats import nbinom

from .base import ScoreMatrix, build_score_grid


def negative_binomial_probabilities(
    expected_score: float,
    alpha: float,
    scores: np.ndarray,
) -> np.ndarray:
    """Calculate Negative Binomial probabilities using NB2 parameterisation.

    Var(X) = mu + alpha * mu^2

    Any probability mass above the maximum score is added to the final
    score bucket, matching the research/backtest implementation.
    """
    if expected_score < 0:
        raise ValueError("expected_score cannot be negative.")

    if alpha < 0:
        raise ValueError("alpha cannot be negative.")

    max_score = int(scores[-1])

    if alpha <= 1e-12:
        raise ValueError(
            "alpha is effectively zero; use the Poisson model instead."
        )

    n = 1.0 / alpha
    p = n / (n + expected_score)

    probabilities = nbinom.pmf(
        scores,
        n,
        p,
    )

    # Preserve the research implementation:
    # put all remaining tail mass into the final bucket.
    probabilities[-1] += max(
        0.0,
        1.0 - probabilities.sum(),
    )

    total_probability = probabilities.sum()

    if not np.isfinite(total_probability) or total_probability <= 0:
        raise ValueError(
            "Negative Binomial probabilities could not be normalised."
        )

    return probabilities / total_probability


def build_negative_binomial_score_matrix(
    expected_home_score: float,
    expected_away_score: float,
    *,
    alpha: float = 0.4,
    max_score: int = 100,
) -> ScoreMatrix:
    """Build an independent Negative Binomial home-away score matrix."""
    scores = build_score_grid(max_score=max_score)

    home_probabilities = negative_binomial_probabilities(
        expected_score=expected_home_score,
        alpha=alpha,
        scores=scores,
    )

    away_probabilities = negative_binomial_probabilities(
        expected_score=expected_away_score,
        alpha=alpha,
        scores=scores,
    )

    probabilities = np.outer(
        home_probabilities,
        away_probabilities,
    )

    probabilities /= probabilities.sum()

    return ScoreMatrix(
        probabilities=probabilities,
        scores=scores,
    )