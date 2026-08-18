"""Generate fixture-level score probability distributions."""

from __future__ import annotations

import numpy as np


def generate_score_probability_matrix(
    historical_matrix: np.ndarray,
    expected_home_score: float,
    expected_away_score: float,
) -> np.ndarray:
    """Tilt a historical score matrix to fixture-specific expected scores.

    Parameters
    ----------
    historical_matrix:
        Base empirical probability matrix where rows represent home scores
        and columns represent away scores.

    expected_home_score:
        Target expected home score for the fixture.

    expected_away_score:
        Target expected away score for the fixture.

    Returns
    -------
    np.ndarray
        Fixture-specific probability matrix summing to 1.
    """
    matrix = np.asarray(historical_matrix, dtype=float)

    if matrix.ndim != 2:
        raise ValueError("historical_matrix must be two-dimensional")

    if np.any(matrix < 0):
        raise ValueError("historical_matrix cannot contain negative probabilities")

    total_probability = matrix.sum()

    if total_probability <= 0:
        raise ValueError("historical_matrix must contain positive probability mass")

    # Ensure the supplied historical matrix is normalized.
    matrix = matrix / total_probability

    home_scores = np.arange(matrix.shape[0], dtype=float)
    away_scores = np.arange(matrix.shape[1], dtype=float)

    home_tilt = _solve_tilt(
        marginal=matrix.sum(axis=1),
        scores=home_scores,
        target_mean=expected_home_score,
    )

    away_tilt = _solve_tilt(
        marginal=matrix.sum(axis=0),
        scores=away_scores,
        target_mean=expected_away_score,
    )

    weights = np.exp(
        home_tilt * home_scores[:, None]
        + away_tilt * away_scores[None, :]
    )

    tilted_matrix = matrix * weights
    tilted_matrix /= tilted_matrix.sum()

    return tilted_matrix


def _solve_tilt(
    marginal: np.ndarray,
    scores: np.ndarray,
    target_mean: float,
    *,
    tolerance: float = 1e-10,
    max_iterations: int = 100,
) -> float:
    """Find the exponential tilt required to achieve a target mean."""
    if target_mean < scores.min() or target_mean > scores.max():
        raise ValueError(
            f"Target mean {target_mean} is outside supported score range "
            f"{scores.min()}-{scores.max()}"
        )

    def tilted_mean(theta: float) -> float:
        log_weights = theta * scores
        log_weights -= log_weights.max()

        weights = marginal * np.exp(log_weights)
        weights /= weights.sum()

        return float(np.sum(scores * weights))

    lower = -10.0
    upper = 10.0

    for _ in range(max_iterations):
        midpoint = (lower + upper) / 2
        mean = tilted_mean(midpoint)

        if abs(mean - target_mean) < tolerance:
            return midpoint

        if mean < target_mean:
            lower = midpoint
        else:
            upper = midpoint

    return (lower + upper) / 2