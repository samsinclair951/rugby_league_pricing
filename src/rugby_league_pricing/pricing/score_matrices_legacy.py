from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import lgamma

import numpy as np
import pandas as pd


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


def poisson_probabilities(
    expected_score: float,
    scores: np.ndarray,
) -> np.ndarray:
    """Calculate a truncated and renormalised Poisson distribution."""
    if expected_score < 0:
        raise ValueError("expected_score cannot be negative.")

    if expected_score == 0:
        probabilities = np.zeros(len(scores), dtype=float)
        probabilities[0] = 1.0
        return probabilities

    log_probabilities = (
        -expected_score
        + scores * np.log(expected_score)
        - np.array([lgamma(int(score) + 1) for score in scores])
    )

    probabilities = np.exp(log_probabilities)
    total_probability = probabilities.sum()

    if total_probability <= 0:
        raise ValueError("Poisson probabilities could not be normalised.")

    return probabilities / total_probability


def build_poisson_score_matrix(
    expected_home_score: float,
    expected_away_score: float,
    max_score: int = 100,
) -> ScoreMatrix:
    """Build an independent Poisson home-away score matrix."""
    scores = build_score_grid(max_score=max_score)

    home_probabilities = poisson_probabilities(
        expected_score=expected_home_score,
        scores=scores,
    )
    away_probabilities = poisson_probabilities(
        expected_score=expected_away_score,
        scores=scores,
    )

    probabilities = np.outer(home_probabilities, away_probabilities)
    probabilities /= probabilities.sum()

    return ScoreMatrix(
        probabilities=probabilities,
        scores=scores,
    )


def build_shifted_historical_score_matrix(
    historical_results: pd.DataFrame,
    expected_home_score: float,
    expected_away_score: float,
    *,
    home_score_column: str = "home_score",
    away_score_column: str = "away_score",
    max_score: int = 100,
    scale_strength: float = 1.0,
) -> ScoreMatrix:
    """
    Build a fixture-specific empirical score matrix.

    Historical scores are scaled relative to historical league scoring
    averages. Probability is distributed between neighbouring integer scores
    using linear interpolation.
    """
    _validate_historical_results(
        historical_results=historical_results,
        home_score_column=home_score_column,
        away_score_column=away_score_column,
    )

    if expected_home_score < 0 or expected_away_score < 0:
        raise ValueError("Expected scores cannot be negative.")

    if not 0 <= scale_strength <= 1:
        raise ValueError("scale_strength must be between 0 and 1.")

    scores = build_score_grid(max_score=max_score)

    historical_home_scores = historical_results[home_score_column].astype(float)
    historical_away_scores = historical_results[away_score_column].astype(float)

    historical_home_mean = float(historical_home_scores.mean())
    historical_away_mean = float(historical_away_scores.mean())

    if historical_home_mean <= 0 or historical_away_mean <= 0:
        raise ValueError("Historical mean scores must be greater than zero.")

    home_scale = _calculate_scale_factor(
        target_mean=expected_home_score,
        historical_mean=historical_home_mean,
        scale_strength=scale_strength,
    )
    away_scale = _calculate_scale_factor(
        target_mean=expected_away_score,
        historical_mean=historical_away_mean,
        scale_strength=scale_strength,
    )

    shifted_home_scores = historical_home_scores.to_numpy() * home_scale
    shifted_away_scores = historical_away_scores.to_numpy() * away_scale

    probabilities = np.zeros(
        shape=(len(scores), len(scores)),
        dtype=float,
    )

    observation_probability = 1.0 / len(historical_results)

    for shifted_home, shifted_away in zip(
        shifted_home_scores,
        shifted_away_scores,
        strict=True,
    ):
        home_allocations = _interpolation_allocations(
            value=shifted_home,
            max_score=max_score,
        )
        away_allocations = _interpolation_allocations(
            value=shifted_away,
            max_score=max_score,
        )

        for home_score, home_weight in home_allocations:
            for away_score, away_weight in away_allocations:
                probabilities[home_score, away_score] += (
                    observation_probability * home_weight * away_weight
                )

    probabilities /= probabilities.sum()

    return ScoreMatrix(
        probabilities=probabilities,
        scores=scores,
    )


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


def _calculate_scale_factor(
    target_mean: float,
    historical_mean: float,
    scale_strength: float,
) -> float:
    """Return a dampened proportional score scale."""
    if target_mean == 0:
        return 0.0

    raw_scale = target_mean / historical_mean
    return raw_scale**scale_strength


def _interpolation_allocations(
    value: float,
    max_score: int,
) -> Iterable[tuple[int, float]]:
    """Allocate a decimal score across adjacent integer score cells."""
    clipped_value = min(max(value, 0.0), float(max_score))

    lower_score = int(np.floor(clipped_value))
    upper_score = int(np.ceil(clipped_value))

    if lower_score == upper_score:
        return ((lower_score, 1.0),)

    upper_weight = clipped_value - lower_score
    lower_weight = 1.0 - upper_weight

    return (
        (lower_score, lower_weight),
        (upper_score, upper_weight),
    )


def _validate_historical_results(
    historical_results: pd.DataFrame,
    home_score_column: str,
    away_score_column: str,
) -> None:
    """Validate historical results used to build the empirical matrix."""
    if historical_results.empty:
        raise ValueError("historical_results cannot be empty.")

    required_columns = {home_score_column, away_score_column}
    missing_columns = required_columns.difference(historical_results.columns)

    if missing_columns:
        raise ValueError(
            "Historical results are missing required columns: "
            f"{sorted(missing_columns)}."
        )

    scores = historical_results[[home_score_column, away_score_column]]

    if scores.isna().any().any():
        raise ValueError("Historical scores cannot contain missing values.")

    if (scores < 0).any().any():
        raise ValueError("Historical scores cannot be negative.")
