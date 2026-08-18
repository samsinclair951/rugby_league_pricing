from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from rugby_league_pricing.pricing.score_distribution.historical import (
    generate_score_probability_matrix,
)
from rugby_league_pricing.pricing.true_prices import (
    MainlineHandicapPricer,
    MainlineTotalsPricer,
    MatchOddsPricer,
)


def _prices_to_frame(prices: list) -> pd.DataFrame:
    return pd.DataFrame(asdict(price) for price in prices)


def price_fixture(
    *,
    historical_matrix,
    expected_home_score: float,
    expected_away_score: float,
) -> dict[str, object]:
    """Generate the dashboard price set for one fixture."""
    score_matrix = generate_score_probability_matrix(
        historical_matrix=historical_matrix,
        expected_home_score=expected_home_score,
        expected_away_score=expected_away_score,
    )

    match_odds = MatchOddsPricer(score_matrix).price()

    handicap_pricer = MainlineHandicapPricer(
        score_matrix=score_matrix,
        expected_home_score=expected_home_score,
        expected_away_score=expected_away_score,
        line_range=20,
    )

    totals_pricer = MainlineTotalsPricer(
        score_matrix=score_matrix,
        expected_home_score=expected_home_score,
        expected_away_score=expected_away_score,
        line_range=20,
    )

    handicap_lines = handicap_pricer.price_all()
    total_lines = totals_pricer.price_all()

    # Display every two points, centred on the model mainline.
    handicap_display_lines = [
        handicap_pricer.mainline + offset
        for offset in range(-20, 21, 2)
    ]
    total_display_lines = [
        totals_pricer.mainline + offset
        for offset in range(-20, 21, 2)
    ]

    return {
        "score_matrix": score_matrix,
        "match_odds": _prices_to_frame(match_odds),
        "main_handicap": handicap_pricer.mainline,
        "handicaps": _market_lines_to_frame(
            handicap_lines,
            handicap_display_lines,
            first_selection="home",
            second_selection="away",
        ),
        "main_total": totals_pricer.mainline,
        "totals": _market_lines_to_frame(
            total_lines,
            total_display_lines,
            first_selection="over",
            second_selection="under",
        ),
    }


def _market_lines_to_frame(
    all_prices: dict[float, list],
    lines: list[float],
    *,
    first_selection: str,
    second_selection: str,
) -> pd.DataFrame:
    rows: list[dict[str, float]] = []

    for line in lines:
        line = float(line)
        selections = all_prices.get(line)

        if selections is None:
            # price_all() may be configured for one-point increments but floating
            # point construction can occasionally create 6.499999999 values.
            matching_key = next(
                (key for key in all_prices if abs(key - line) < 1e-9),
                None,
            )
            if matching_key is None:
                continue
            selections = all_prices[matching_key]

        by_selection = {price.selection: price for price in selections}
        first = by_selection[first_selection]
        second = by_selection[second_selection]

        rows.append(
            {
                "line": line,
                f"{first_selection}_probability": first.probability,
                f"{first_selection}_price": first.decimal_price,
                f"{second_selection}_probability": second.probability,
                f"{second_selection}_price": second.decimal_price,
            }
        )

    return pd.DataFrame(rows)
