from __future__ import annotations

import numpy as np
import pandas as pd

from .base import ScoreMatrix
from .poisson import build_poisson_score_matrix
from ..score_matrices_legacy import build_shifted_historical_score_matrix


def blend_score_matrices(
    poisson_matrix: ScoreMatrix,
    historical_matrix: ScoreMatrix,
    *,
    historical_weight: float,
) -> ScoreMatrix:
    """Blend Poisson and shifted historical score matrices."""
    if not 0 <= historical_weight <= 1:
        raise ValueError("historical_weight must be between 0 and 1.")

    if not np.array_equal(poisson_matrix.scores, historical_matrix.scores):
        raise ValueError("Both matrices must use the same score grid.")

    probabilities = (
        (1 - historical_weight) * poisson_matrix.probabilities
        + historical_weight * historical_matrix.probabilities
    )
    probabilities /= probabilities.sum()

    return ScoreMatrix(
        probabilities=probabilities,
        scores=poisson_matrix.scores.copy(),
    )


def build_blended_score_matrix(
    historical_results: pd.DataFrame,
    expected_home_score: float,
    expected_away_score: float,
    *,
    max_score: int = 100,
    historical_weight: float = 0.20,
    scale_strength: float = 1.0,
    home_score_column: str = "home_score",
    away_score_column: str = "away_score",
) -> ScoreMatrix:
    """Build the complete Poisson-historical blended score matrix."""
    poisson_matrix = build_poisson_score_matrix(
        expected_home_score=expected_home_score,
        expected_away_score=expected_away_score,
        max_score=max_score,
    )

    historical_matrix = build_shifted_historical_score_matrix(
        historical_results=historical_results,
        expected_home_score=expected_home_score,
        expected_away_score=expected_away_score,
        home_score_column=home_score_column,
        away_score_column=away_score_column,
        max_score=max_score,
        scale_strength=scale_strength,
    )

    return blend_score_matrices(
        poisson_matrix=poisson_matrix,
        historical_matrix=historical_matrix,
        historical_weight=historical_weight,
    )
