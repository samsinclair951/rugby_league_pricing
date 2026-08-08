from __future__ import annotations

import numpy as np

from rugby_league_pricing.pricing.true_prices.base import (
    BasePricer,
    MarketPrice,
)


class MatchOddsPricer(BasePricer):
    """Price home win, draw, and away win markets."""

    def price(self) -> list[MarketPrice]:
        """Return fair match odds prices."""
        home_probability = float(
            np.tril(self.score_matrix, k=-1).sum()
        )
        draw_probability = float(np.trace(self.score_matrix))
        away_probability = float(
            np.triu(self.score_matrix, k=1).sum()
        )

        return [
            self._make_price(
                market="match_odds",
                selection="home",
                probability=home_probability,
            ),
            self._make_price(
                market="match_odds",
                selection="draw",
                probability=draw_probability,
            ),
            self._make_price(
                market="match_odds",
                selection="away",
                probability=away_probability,
            ),
        ]