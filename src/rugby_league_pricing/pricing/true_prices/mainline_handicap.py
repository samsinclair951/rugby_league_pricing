from __future__ import annotations

import numpy as np

from rugby_league_pricing.pricing.true_prices.base import (
    BasePricer,
    MarketPrice,
)


class MainlineHandicapPricer(BasePricer):
    """Price handicap markets around the expected score difference."""

    def __init__(
        self,
        score_matrix: np.ndarray,
        expected_home_score: float,
        expected_away_score: float,
        *,
        line_range: int = 20,
    ) -> None:
        super().__init__(score_matrix)

        if line_range < 0:
            raise ValueError("line_range cannot be negative")

        self.expected_home_score = expected_home_score
        self.expected_away_score = expected_away_score
        self.line_range = line_range

    @property
    def expected_score_difference(self) -> float:
        """Return expected home score minus expected away score."""
        return self.expected_home_score - self.expected_away_score

    @property
    def mainline(self) -> float:
        """Return the nearest half-point handicap to the expected margin.

        Handicap lines are expressed from the home team's perspective.

        A positive expected home margin therefore produces a negative
        home handicap.

        Example
        -------
        Expected scores:
            Home = 28.4
            Away = 21.7

        Expected margin:
            +6.7

        Main handicap:
            Home -6.5
        """
        expected_handicap = -self.expected_score_difference

        return np.floor(expected_handicap) + 0.5

    def price_line(self, line: float) -> list[MarketPrice]:
        """Price a single two-way handicap market."""
        home_scores, away_scores = np.indices(
            self.score_matrix.shape
        )

        home_probability = float(
            self.score_matrix[
                home_scores + line > away_scores
            ].sum()
        )
        away_probability = 1.0 - home_probability

        return [
            self._make_price(
                market="handicap",
                selection="home",
                line=line,
                probability=home_probability,
            ),
            self._make_price(
                market="handicap",
                selection="away",
                line=line,
                probability=away_probability,
            ),
        ]

    def price_mainline(self) -> list[MarketPrice]:
        """Price the main handicap line."""
        return self.price_line(self.mainline)

    def price_all(self) -> dict[float, list[MarketPrice]]:
        """Price handicap lines 20 points either side of the mainline."""
        lines = np.arange(
            self.mainline - self.line_range,
            self.mainline + self.line_range + 1.0,
            1.0,
        )

        return {
            float(line): self.price_line(float(line))
            for line in lines
        }