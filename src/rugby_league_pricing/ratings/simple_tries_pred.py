from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.stats import poisson

POINTS_PER_TRY = 5.2
DEFAULT_MAX_TRIES = 16


@dataclass(frozen=True)
class MatchPrediction:
    home_team: str
    away_team: str
    expected_home_tries: float
    expected_away_tries: float
    home_win_probability: float
    draw_probability: float
    away_win_probability: float
    probability_matrix: pd.DataFrame


def load_results(csv_path: str | Path) -> pd.DataFrame:
    """Load and validate the historical match results."""
    results = pd.read_csv(csv_path)

    # Remove an index column created by older pandas CSV exports.
    results = results.drop(columns=["Unnamed: 0"], errors="ignore")

    required_columns = {"year", "home", "away", "homescore", "awayscore"}
    missing_columns = required_columns.difference(results.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"CSV is missing required columns: {missing}")

    results = results.dropna(subset=list(required_columns)).copy()
    results["year"] = results["year"].astype(int)

    return results


def prepare_model_data(
    results: pd.DataFrame,
    year: int,
    points_per_try: float = POINTS_PER_TRY,
) -> pd.DataFrame:
    """Convert one row per match into one row per team performance."""
    season = results.loc[
        results["year"].eq(year),
        ["home", "away", "homescore", "awayscore"],
    ].copy()

    if season.empty:
        raise ValueError(f"No matches found for year {year}")

    home_rows = pd.DataFrame(
        {
            "team": season["home"],
            "opponent": season["away"],
            "is_home": 1,
            "tries": season["homescore"] / points_per_try,
        }
    )

    away_rows = pd.DataFrame(
        {
            "team": season["away"],
            "opponent": season["home"],
            "is_home": 0,
            "tries": season["awayscore"] / points_per_try,
        }
    )

    return pd.concat([home_rows, away_rows], ignore_index=True)


def fit_poisson_model(model_data: pd.DataFrame):
    """Fit a Poisson model using attack, defence, and home advantage."""
    return smf.glm(
        formula="tries ~ is_home + C(team) + C(opponent)",
        data=model_data,
        family=sm.families.Poisson(),
    ).fit()


def expected_tries(model, team: str, opponent: str, is_home: bool) -> float:
    """Predict a team's expected tries for a fixture."""
    prediction_data = pd.DataFrame(
        {
            "team": [team],
            "opponent": [opponent],
            "is_home": [int(is_home)],
        }
    )

    try:
        return float(model.predict(prediction_data).iloc[0])
    except Exception as exc:
        raise ValueError(
            f"Could not predict {team} vs {opponent}. "
            "Check that both teams appear in the fitted season."
        ) from exc


def create_probability_matrix(
    expected_home_tries: float,
    expected_away_tries: float,
    max_tries: int = DEFAULT_MAX_TRIES,
) -> pd.DataFrame:
    """Create the joint probability matrix for home and away tries."""
    try_counts = np.arange(max_tries + 1)

    home_probabilities = poisson.pmf(try_counts, expected_home_tries)
    away_probabilities = poisson.pmf(try_counts, expected_away_tries)

    matrix = np.outer(home_probabilities, away_probabilities)

    return pd.DataFrame(
        matrix,
        index=pd.Index(try_counts, name="home_tries"),
        columns=pd.Index(try_counts, name="away_tries"),
    )


def predict_match(
    model,
    home_team: str,
    away_team: str,
    max_tries: int = DEFAULT_MAX_TRIES,
) -> MatchPrediction:
    """Generate expected tries and result probabilities for one match."""
    home_mean = expected_tries(model, home_team, away_team, is_home=True)
    away_mean = expected_tries(model, away_team, home_team, is_home=False)

    matrix = create_probability_matrix(home_mean, away_mean, max_tries)

    values = matrix.to_numpy()
    home_win_probability = float(np.tril(values, k=-1).sum())
    draw_probability = float(np.trace(values))
    away_win_probability = float(np.triu(values, k=1).sum())

    # A finite matrix omits a tiny tail above max_tries, so normalise.
    total_probability = home_win_probability + draw_probability + away_win_probability
    home_win_probability /= total_probability
    draw_probability /= total_probability
    away_win_probability /= total_probability

    return MatchPrediction(
        home_team=home_team,
        away_team=away_team,
        expected_home_tries=home_mean,
        expected_away_tries=away_mean,
        home_win_probability=home_win_probability,
        draw_probability=draw_probability,
        away_win_probability=away_win_probability,
        probability_matrix=matrix,
    )


def print_prediction(prediction: MatchPrediction) -> None:
    """Print a readable summary."""
    print(f"\n{prediction.home_team} vs {prediction.away_team}")
    print(
        f"Expected tries: "
        f"{prediction.home_team} {prediction.expected_home_tries:.2f}, "
        f"{prediction.away_team} {prediction.expected_away_tries:.2f}"
    )
    print(f"Home win: {prediction.home_win_probability:.1%}")
    print(f"Draw:     {prediction.draw_probability:.1%}")
    print(f"Away win: {prediction.away_win_probability:.1%}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fit a Poisson tries model and predict one fixture."
    )
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("year", type=int)
    parser.add_argument("home_team")
    parser.add_argument("away_team")
    parser.add_argument("--max-tries", type=int, default=DEFAULT_MAX_TRIES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    results = load_results(args.csv_path)
    model_data = prepare_model_data(results, args.year)
    model = fit_poisson_model(model_data)

    prediction = predict_match(
        model=model,
        home_team=args.home_team,
        away_team=args.away_team,
        max_tries=args.max_tries,
    )

    print_prediction(prediction)


if __name__ == "__main__":
    main()
