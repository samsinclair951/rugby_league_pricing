from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from rugby_league_pricing.pricing.score_matrices.blend import (
    build_blended_score_matrix,
)
from rugby_league_pricing.pricing.true_prices.mainline_handicap import (
    MainlineHandicapPricer,
)
from rugby_league_pricing.pricing.true_prices.mainline_totals import (
    MainlineTotalsPricer,
)
from rugby_league_pricing.pricing.true_prices.match_odds import (
    MatchOddsPricer,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = REPO_ROOT / "data" / "rugby_league_pricing.db"

MODEL_VERSION = "negative-binomial-historical-v1"


def load_predictions(
    connection: sqlite3.Connection,
    fixture_id: str,
) -> pd.DataFrame:
    predictions = pd.read_sql_query(
        """
        SELECT
            esp.fixture_id,
            esp.version_type,
            esp.home_team_id,
            esp.away_team_id,
            esp.expected_home_score,
            esp.expected_away_score,
            f.match_date
        FROM expected_score_predictions esp
        JOIN fixtures f
            ON f.fixture_id = esp.fixture_id
        WHERE esp.fixture_id = ?
        ORDER BY esp.version_type
        """,
        connection,
        params=(fixture_id,),
        parse_dates=["match_date"],
    )

    if predictions.empty:
        raise ValueError(
            f"No expected-score predictions found for {fixture_id}"
        )

    return predictions


def load_historical_results(
    connection: sqlite3.Connection,
    before_date: pd.Timestamp,
) -> pd.DataFrame:
    results = pd.read_sql_query(
        """
        SELECT
            r.home_score,
            r.away_score
        FROM results r
        JOIN fixtures f
            ON f.fixture_id = r.fixture_id
        WHERE f.match_date < ?
          AND r.home_score IS NOT NULL
          AND r.away_score IS NOT NULL
        ORDER BY f.match_date
        """,
        connection,
        params=(before_date.strftime("%Y-%m-%d"),),
    )

    if results.empty:
        raise ValueError(
            f"No historical results found before {before_date.date()}"
        )

    return results


def build_price_records(
    *,
    fixture_id: str,
    version_type: str,
    expected_home_score: float,
    expected_away_score: float,
    prices,
) -> list[dict]:
    """Convert MarketPrice objects into rows for true_prices."""
    generated_at = datetime.now(timezone.utc).isoformat()

    records = []

    for price in prices:
        records.append(
            {
                "fixture_id": fixture_id,
                "version_type": version_type,
                "market": price.market,
                "selection": price.selection,
                "line": (
                    0.0
                    if price.line is None
                    else float(price.line)
                ),
                "probability": float(price.probability),
                "decimal_price": float(price.decimal_price),
                "expected_home_score": expected_home_score,
                "expected_away_score": expected_away_score,
                "model_version": MODEL_VERSION,
                "generated_at": generated_at,
            }
        )

    return records


def upsert_true_prices(
    connection: sqlite3.Connection,
    records: list[dict],
) -> None:
    """Insert or update generated true prices."""
    connection.executemany(
        """
        INSERT INTO true_prices (
            fixture_id,
            version_type,
            market,
            selection,
            line,
            probability,
            decimal_price,
            expected_home_score,
            expected_away_score,
            model_version,
            generated_at
        )
        VALUES (
            :fixture_id,
            :version_type,
            :market,
            :selection,
            :line,
            :probability,
            :decimal_price,
            :expected_home_score,
            :expected_away_score,
            :model_version,
            :generated_at
        )
        ON CONFLICT (
            fixture_id,
            version_type,
            market,
            selection,
            line
        )
        DO UPDATE SET
            probability = excluded.probability,
            decimal_price = excluded.decimal_price,
            expected_home_score = excluded.expected_home_score,
            expected_away_score = excluded.expected_away_score,
            model_version = excluded.model_version,
            generated_at = excluded.generated_at
        """,
        records,
    )

    connection.commit()


def print_prices(
    version_type: str,
    expected_home_score: float,
    expected_away_score: float,
    match_odds,
    handicap,
    totals,
    handicap_line: float,
    totals_line: float,
) -> None:
    print()
    print("=" * 70)
    print(version_type)
    print("=" * 70)

    print(
        f"Expected score: "
        f"{expected_home_score:.2f} - {expected_away_score:.2f}"
    )

    print()
    print("MATCH ODDS")
    for price in match_odds:
        print(price)

    print()
    print(f"HANDICAP MAINLINE: {handicap_line:+.1f}")
    for price in handicap:
        print(price)

    print()
    print(f"TOTALS MAINLINE: {totals_line:.1f}")
    for price in totals:
        print(price)


def price_fixture(
    connection: sqlite3.Connection,
    fixture_id: str,
    *,
    alpha: float = 0.40,
    historical_weight: float = 0.60,
    max_score: int = 100,
) -> None:
    predictions = load_predictions(
        connection=connection,
        fixture_id=fixture_id,
    )

    fixture_date = pd.Timestamp(
        predictions.iloc[0]["match_date"]
    )

    historical_results = load_historical_results(
        connection=connection,
        before_date=fixture_date,
    )

    print(
        f"Pricing {fixture_id} using "
        f"{len(historical_results):,} historical matches."
    )

    for prediction in predictions.itertuples(index=False):
        version_type = str(prediction.version_type)

        expected_home_score = float(
            prediction.expected_home_score
        )
        expected_away_score = float(
            prediction.expected_away_score
        )

        score_matrix = build_blended_score_matrix(
            historical_results=historical_results,
            expected_home_score=expected_home_score,
            expected_away_score=expected_away_score,
            alpha=alpha,
            historical_weight=historical_weight,
            max_score=max_score,
        )

        probabilities = score_matrix.probabilities

        match_odds = MatchOddsPricer(
            probabilities
        ).price()

        handicap_pricer = MainlineHandicapPricer(
            probabilities,
            expected_home_score=expected_home_score,
            expected_away_score=expected_away_score,
        )

        totals_pricer = MainlineTotalsPricer(
            probabilities,
            expected_home_score=expected_home_score,
            expected_away_score=expected_away_score,
        )

        handicap = handicap_pricer.price_mainline()
        totals = totals_pricer.price_mainline()

        all_prices = [
            *match_odds,
            *handicap,
            *totals,
        ]

        records = build_price_records(
            fixture_id=fixture_id,
            version_type=version_type,
            expected_home_score=expected_home_score,
            expected_away_score=expected_away_score,
            prices=all_prices,
        )

        upsert_true_prices(
            connection=connection,
            records=records,
        )

        print_prices(
            version_type=version_type,
            expected_home_score=expected_home_score,
            expected_away_score=expected_away_score,
            match_odds=match_odds,
            handicap=handicap,
            totals=totals,
            handicap_line=float(handicap_pricer.mainline),
            totals_line=float(totals_pricer.mainline),
        )

        print(
            f"\nSaved {len(records)} true-price rows "
            f"for {version_type}."
        )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--fixture-id",
        required=True,
    )

    parser.add_argument(
        "--alpha",
        type=float,
        default=0.40,
    )

    parser.add_argument(
        "--historical-weight",
        type=float,
        default=0.60,
    )

    parser.add_argument(
        "--max-score",
        type=int,
        default=100,
    )

    args = parser.parse_args()

    with sqlite3.connect(DATABASE_PATH) as connection:
        price_fixture(
            connection=connection,
            fixture_id=args.fixture_id,
            alpha=args.alpha,
            historical_weight=args.historical_weight,
            max_score=args.max_score,
        )


if __name__ == "__main__":
    main()
