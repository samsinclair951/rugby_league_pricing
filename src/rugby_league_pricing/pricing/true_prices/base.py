from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MarketPrice:
    """Probability and decimal price for a market selection."""

    market: str
    selection: str
    probability: float
    decimal_price: float
    line: float | None = None


class BasePricer:
    """Base class for pricing markets from a score probability matrix."""

    def __init__(self, score_matrix: np.ndarray) -> None:
        self.score_matrix = self._validate_matrix(score_matrix)

    @staticmethod
    def _validate_matrix(score_matrix: np.ndarray) -> np.ndarray:
        """Validate and normalise a score probability matrix."""
        matrix = np.asarray(score_matrix, dtype=float)

        if matrix.ndim != 2:
            raise ValueError("score_matrix must be two-dimensional")

        if np.any(matrix < 0):
            raise ValueError(
                "score_matrix cannot contain negative probabilities"
            )

        total_probability = matrix.sum()

        if total_probability <= 0:
            raise ValueError(
                "score_matrix must contain positive probability mass"
            )

        return matrix / total_probability

    @staticmethod
    def _decimal_price(probability: float) -> float:
        """Convert probability to fair decimal odds."""
        if probability <= 0:
            return float("inf")

        return 1.0 / probability

    @classmethod
    def _make_price(
        cls,
        *,
        market: str,
        selection: str,
        probability: float,
        line: float | None = None,
    ) -> MarketPrice:
        """Create a market price object."""
        return MarketPrice(
            market=market,
            selection=selection,
            line=line,
            probability=probability,
            decimal_price=cls._decimal_price(probability),
        )