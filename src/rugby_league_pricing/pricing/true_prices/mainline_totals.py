from __future__ import annotations

import numpy as np

from rugby_league_pricing.pricing.true_prices.base import (
    BasePricer,
    MarketPrice,
)


class MainlineTotalsPricer(BasePricer):
    """Price total points markets and identify the main total."""

    def __init__(
        self,
        score_matrix: np.ndarray,
        *,
        line_range: float = 20.0,
    ) -> None:
        super().__init__(score_matrix)

        if line_range <= 0:
            raise ValueError("line_range must be positive")

        self.line_range = line_range

    def price_all(self) -> dict[float, list[MarketPrice]]:
        """Price total lines around the expected match total."""
        home_scores, away_scores = np.indices(
            self.score_matrix.shape
        )
        total_scores = home_scores + away_scores

        expected_total = float(
            (self.score_matrix * total_scores).sum()
        )

        minimum_line = (
            np.floor(expected_total - self.line_range) + 0.5
        )
        maximum_line = (
            np.ceil(expected_total + self.line_range) + 0.5
        )

        lines = np.arange(
            minimum_line,
            maximum_line + 1.0,
            1.0,
        )

        prices: dict[float, list[MarketPrice]] = {}

        for line in lines:
            line = float(line)

            over_probability = float(
                self.score_matrix[
                    total_scores > line
                ].sum()
            )
            under_probability = 1.0 - over_probability

            prices[line] = [
                self._make_price(
                    market="total",
                    selection="over",
                    line=line,
                    probability=over_probability,
                ),
                self._make_price(
                    market="total",
                    selection="under",
                    line=line,
                    probability=under_probability,
                ),
            ]

        return prices

    def price_mainline(self) -> list[MarketPrice]:
        """Return the total line closest to a 50/50 market."""
        prices = self.price_all()

        main_line = min(
            prices,
            key=lambda line: abs(
                prices[line][0].probability - 0.5
            ),
        )

        return prices[main_line]