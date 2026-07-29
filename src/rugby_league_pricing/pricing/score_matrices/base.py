from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ScoreMatrix:
    """A joint probability distribution over home and away scores."""

    probabilities: np.ndarray
    scores: np.ndarray

    def __post_init__(self) -> None:
        expected_shape = (len(self.scores), len(self.scores))

        if self.probabilities.shape != expected_shape:
            raise ValueError(
                "Probability matrix shape must match the score grid: "
                f"expected {expected_shape}, got {self.probabilities.shape}."
            )

        if np.any(self.probabilities < 0):
            raise ValueError("Probability matrix cannot contain negative values.")

        total_probability = float(self.probabilities.sum())

        if not np.isclose(total_probability, 1.0):
            raise ValueError(
                "Probability matrix must sum to 1. "
                f"Current sum is {total_probability:.12f}."
            )

    @property
    def expected_home_score(self) -> float:
        """Return the expected home score implied by the matrix."""
        home_probabilities = self.probabilities.sum(axis=1)
        return float(np.dot(self.scores, home_probabilities))

    @property
    def expected_away_score(self) -> float:
        """Return the expected away score implied by the matrix."""
        away_probabilities = self.probabilities.sum(axis=0)
        return float(np.dot(self.scores, away_probabilities))


def build_score_grid(max_score: int = 100) -> np.ndarray:
    """Return an integer score grid from zero to ``max_score``."""
    if max_score < 1:
        raise ValueError("max_score must be at least 1.")

    return np.arange(max_score + 1, dtype=int)
