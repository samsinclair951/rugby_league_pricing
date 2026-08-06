from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import DEFAULT_FORM_WINDOW, DEFAULT_ITERATIONS, DEFAULT_PRIOR_GAMES


def add_league_average(
    recent_form: pd.DataFrame,
    league_window: int,
) -> pd.DataFrame:
    """
    Add the average points scored per team across recent fixtures.

    The current fixture is excluded, so the value is available before
    the match takes place.
    """
    if league_window <= 0:
        raise ValueError("League window must be positive.")

    fixture_scores = (
        recent_form.groupby(
            [
                "fixture_id",
                "match_date",
            ],
            as_index=False,
        )
        .agg(
            fixture_average_points=(
                "points_for",
                "mean",
            )
        )
        .sort_values(
            [
                "match_date",
                "fixture_id",
            ]
        )
        .reset_index(drop=True)
    )

    fixture_scores["league_average_points"] = (
        fixture_scores["fixture_average_points"]
        .shift(1)
        .rolling(
            window=league_window,
            min_periods=1,
        )
        .mean()
    )

    return recent_form.merge(
        fixture_scores[
            [
                "fixture_id",
                "league_average_points",
            ]
        ],
        on="fixture_id",
        how="left",
        validate="many_to_one",
    )


def add_opponent_recent_form(
    recent_form: pd.DataFrame,
    form_window: int,
) -> pd.DataFrame:
    """Attach the opponent's pre-match recent-form values."""
    required_columns = {
        f"recent_points_for_{form_window}",
        f"recent_points_against_{form_window}",
        f"recent_games_used_{form_window}",
    }

    missing_columns = required_columns.difference(recent_form.columns)

    if missing_columns:
        raise ValueError(f"Recent form is missing columns: {sorted(missing_columns)}")

    opponent_form = recent_form[
        [
            "fixture_id",
            "team_id",
            f"recent_points_for_{form_window}",
            f"recent_points_against_{form_window}",
            f"recent_games_used_{form_window}",
        ]
    ].rename(
        columns={
            "team_id": "opponent_id",
            (f"recent_points_for_{form_window}"): "opponent_recent_points_for",
            (f"recent_points_against_{form_window}"): "opponent_recent_points_against",
            (f"recent_games_used_{form_window}"): "opponent_recent_games_used",
        }
    )

    return recent_form.merge(
        opponent_form,
        on=[
            "fixture_id",
            "opponent_id",
        ],
        how="left",
        validate="one_to_one",
    )


def shrink_average(
    observed_average: pd.Series,
    games_used: pd.Series,
    league_average: pd.Series,
    prior_games: int,
) -> pd.Series:
    """
    Pull small-sample averages towards the league average.

    For example, with three prior games, one observed match receives
    25% weight and the league average receives 75% weight.
    """
    observed_average = observed_average.fillna(league_average)

    games_used = games_used.fillna(0)

    return ((observed_average * games_used) + (league_average * prior_games)) / (
        games_used + prior_games
    )


def smooth_scale_multiplier(
    raw_multiplier: pd.Series,
    cap_start: float,
    max_edit: float,
    learning_rate: float,
    neutral_multiplier: float = 1.0,
) -> pd.Series:
    """Curve multiplier changes away from the neutral value."""
    if cap_start <= 0:
        raise ValueError("Curve cap start must be positive.")

    if max_edit <= 0:
        raise ValueError("Curve maximum edit must be positive.")

    if learning_rate <= 0:
        raise ValueError("Curve learning rate must be positive.")

    raw_edit = (
        raw_multiplier - neutral_multiplier
    ) * learning_rate

    curve_position = (
        raw_edit.abs() / cap_start
    ).clip(upper=1.0)

    scaled_magnitude = max_edit * (
        (2.0 * curve_position) - curve_position.pow(2)
    )

    return (
        neutral_multiplier
        + np.sign(raw_edit) * scaled_magnitude
    )


def add_raw_multipliers(
    recent_form: pd.DataFrame,
    form_window: int = DEFAULT_FORM_WINDOW,
    prior_games: int = DEFAULT_PRIOR_GAMES,
) -> pd.DataFrame:
    """
    Calculate pre-match raw attack and defence multipliers.

    An attack multiplier above 1 means better-than-average scoring.

    A defence multiplier below 1 means better-than-average defence.
    """
    if prior_games <= 0:
        raise ValueError("Prior games must be positive.")

    strength = recent_form.copy()

    games_column = f"recent_games_used_{form_window}"
    points_for_column = f"recent_points_for_{form_window}"
    points_against_column = f"recent_points_against_{form_window}"

    strength["shrunk_points_for"] = shrink_average(
        observed_average=strength[points_for_column],
        games_used=strength[games_column],
        league_average=strength["league_average_points"],
        prior_games=prior_games,
    )
    strength["shrunk_points_against"] = shrink_average(
        observed_average=strength[points_against_column],
        games_used=strength[games_column],
        league_average=strength["league_average_points"],
        prior_games=prior_games,
    )
    strength["raw_attack_multiplier"] = (
        strength["shrunk_points_for"]
        / strength["league_average_points"]
    )
    strength["raw_defence_multiplier"] = (
        strength["shrunk_points_against"]
        / strength["league_average_points"]
    )
    return strength


def add_opponent_multipliers(strength: pd.DataFrame) -> pd.DataFrame:
    """Attach the opponent's current pre-match strength multipliers."""
    columns_to_remove = [
        "opponent_attack_multiplier",
        "opponent_defence_multiplier",
    ]

    strength = strength.drop(
        columns=[column for column in columns_to_remove if column in strength.columns]
    )

    opponent_strength = strength[
        [
            "fixture_id",
            "team_id",
            "attack_multiplier",
            "defence_multiplier",
        ]
    ].rename(
        columns={
            "team_id": "opponent_id",
            "attack_multiplier": "opponent_attack_multiplier",
            "defence_multiplier": "opponent_defence_multiplier",
        }
    )

    strength = strength.merge(
        opponent_strength,
        on=[
            "fixture_id",
            "opponent_id",
        ],
        how="left",
        validate="one_to_one",
    )

    strength["opponent_attack_multiplier"] = strength[
        "opponent_attack_multiplier"
    ].fillna(1.0)

    strength["opponent_defence_multiplier"] = strength[
        "opponent_defence_multiplier"
    ].fillna(1.0)

    return strength


def add_adjusted_performances(strength: pd.DataFrame) -> pd.DataFrame:
    """
    Adjust each performance using the opponent's current strength.

    Scoring against a strong defence is rewarded.

    Conceding against a strong attack is treated less harshly.
    """
    adjusted = strength.copy()

    adjusted["adjusted_points_for"] = (
        adjusted["points_for"] / adjusted["opponent_defence_multiplier"]
    )

    adjusted["adjusted_points_against"] = (
        adjusted["points_against"] / adjusted["opponent_attack_multiplier"]
    )

    return adjusted


def add_strength_multipliers(
    strength: pd.DataFrame,
    form_window: int = DEFAULT_FORM_WINDOW,
    prior_games: int = DEFAULT_PRIOR_GAMES,
) -> pd.DataFrame:
    """
    Calculate final pre-match opponent-adjusted multipliers.

    The current match is shifted out of the rolling calculation.
    """
    ordered = strength.sort_values(
        [
            "team_id",
            "match_date",
            "fixture_id",
        ]
    ).copy()

    grouped = ordered.groupby("team_id", sort=False)

    ordered["adjusted_points_for_average"] = grouped["adjusted_points_for"].transform(
        lambda values: values.shift(1).rolling(window=form_window, min_periods=1).mean()
    )

    ordered["adjusted_points_against_average"] = grouped[
        "adjusted_points_against"
    ].transform(
        lambda values: values.shift(1).rolling(window=form_window, min_periods=1).mean()
    )

    adjusted_games_used = (
        grouped["adjusted_points_for"]
        .transform(
            lambda values: (
                values.shift(1).rolling(window=form_window, min_periods=1).count()
            )
        )
        .fillna(0)
    )

    ordered["strength_games_used"] = adjusted_games_used.astype(int)

    ordered["adjusted_points_for_average"] = shrink_average(
        observed_average=ordered["adjusted_points_for_average"],
        games_used=ordered["strength_games_used"],
        league_average=ordered["league_average_points"],
        prior_games=prior_games,
    )

    ordered["adjusted_points_against_average"] = shrink_average(
        observed_average=ordered["adjusted_points_against_average"],
        games_used=ordered["strength_games_used"],
        league_average=ordered["league_average_points"],
        prior_games=prior_games,
    )

    ordered["attack_multiplier"] = (
        ordered["adjusted_points_for_average"] / ordered["league_average_points"]
    )

    ordered["defence_multiplier"] = (
        ordered["adjusted_points_against_average"] / ordered["league_average_points"]
    )

    return ordered.reset_index(drop=True)


def iterate_strength_multipliers(
    strength: pd.DataFrame,
    form_window: int = DEFAULT_FORM_WINDOW,
    prior_games: int = DEFAULT_PRIOR_GAMES,
    iterations: int = DEFAULT_ITERATIONS,
    tolerance: float = 0.0001,
    curve_cap_start: float = 0.75,
    curve_max_edit: float = 0.40,
    curve_learning_rate: float = 0.80,
) -> pd.DataFrame:
    """
    Repeatedly refine attack and defence strength multipliers.

    The first pass starts from the raw attack and defence multipliers,
    which are calculated from recent form relative to the league average.

    Each iteration then:

        1. Attaches the opponent's current attack and defence multipliers.
        2. Adjusts each historical performance for opponent quality.
        3. Recalculates attack and defence multipliers from the adjusted
           performances.

    This process is repeated several times because the opponent ratings
    themselves are also estimates. As the iterations progress, the
    multipliers become increasingly self-consistent and converge towards
    stable values. In practice, five iterations are sufficient for the
    ratings to change by only negligible amounts.
    """
    if iterations <= 0:
        raise ValueError("Iterations must be positive.")

    iterative_strength = strength.copy()

    iterative_strength["attack_multiplier"] = iterative_strength[
        "raw_attack_multiplier"
    ]

    iterative_strength["defence_multiplier"] = iterative_strength[
        "raw_defence_multiplier"
    ]

    for _ in range(iterations):
        previous_attack = iterative_strength["attack_multiplier"].copy()
        previous_defence = iterative_strength["defence_multiplier"].copy()

        iterative_strength = add_opponent_multipliers(strength=iterative_strength)
        iterative_strength = add_adjusted_performances(strength=iterative_strength)

        iterative_strength = add_strength_multipliers(
            strength=iterative_strength,
            form_window=form_window,
            prior_games=prior_games,
        )

        maximum_change = max(
            (iterative_strength["attack_multiplier"] - previous_attack).abs().max(),
            (iterative_strength["defence_multiplier"] - previous_defence).abs().max(),
        )

        if maximum_change < tolerance:
            break


    iterative_strength["scaled_attack_multiplier"] = smooth_scale_multiplier(
        raw_multiplier=iterative_strength["attack_multiplier"],
        cap_start=curve_cap_start,
        max_edit=curve_max_edit,
        learning_rate=curve_learning_rate,
    )

    iterative_strength["scaled_defence_multiplier"] = smooth_scale_multiplier(
        raw_multiplier=iterative_strength["defence_multiplier"],
        cap_start=curve_cap_start,
        max_edit=curve_max_edit,
        learning_rate=curve_learning_rate,
    )
    return iterative_strength
