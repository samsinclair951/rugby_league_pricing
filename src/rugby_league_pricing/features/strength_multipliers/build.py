from __future__ import annotations

import sqlite3

import pandas as pd

from .constants import (
    DEFAULT_FORM_WINDOW,
    DEFAULT_ITERATIONS,
    DEFAULT_LEAGUE_WINDOW,
    DEFAULT_PRIOR_GAMES,
    RECENT_FORM_QUERY,
)
from .core import (
    add_league_average,
    add_opponent_recent_form,
    add_raw_multipliers,
    iterate_strength_multipliers,
)
from .upsert import upsert_strength_multipliers

DEFAULT_CURVE_CAP_START = 0.75
DEFAULT_CURVE_MAX_EDIT = 0.40
DEFAULT_CURVE_LEARNING_RATE = 0.80


def load_recent_form(connection: sqlite3.Connection) -> pd.DataFrame:
    """Load completed team performances and recent-form features."""
    recent_form = pd.read_sql_query(
        RECENT_FORM_QUERY,
        connection,
    )

    if recent_form.empty:
        raise ValueError("No recent-form rows were found.")

    recent_form["match_date"] = pd.to_datetime(
        recent_form["match_date"],
        errors="raise",
    )

    return recent_form


def add_upcoming_fixture_rows(
    connection: sqlite3.Connection,
    recent_form: pd.DataFrame,
) -> pd.DataFrame:
    """Add pre-match recent-form rows for fixtures without results."""

    upcoming = pd.read_sql_query(
        """
        SELECT
            f.fixture_id,
            f.match_date,
            f.season,
            f.home_team_id,
            f.away_team_id
        FROM fixtures f
        LEFT JOIN results r
            ON r.fixture_id = f.fixture_id
        WHERE r.fixture_id IS NULL
        ORDER BY f.match_date, f.fixture_id
        """,
        connection,
        parse_dates=["match_date"],
    )

    if upcoming.empty:
        return recent_form

    rows = []

    for fixture in upcoming.itertuples(index=False):
        teams = [
            (
                int(fixture.home_team_id),
                int(fixture.away_team_id),
                1,
            ),
            (
                int(fixture.away_team_id),
                int(fixture.home_team_id),
                0,
            ),
        ]

        for team_id, opponent_id, is_home in teams:
            history = (
                recent_form.loc[
                    (recent_form["team_id"] == team_id)
                    & (
                        recent_form["match_date"]
                        < fixture.match_date
                    )
                ]
                .sort_values("match_date")
            )

            row = {
                "fixture_id": fixture.fixture_id,
                "team_id": team_id,
                "opponent_id": opponent_id,
                "is_home": is_home,
                "match_date": fixture.match_date,
                "season": int(fixture.season),

                # No result yet.
                "points_for": float("nan"),
                "points_against": float("nan"),

                "history_games_before": len(history),
            }

            for window in (5, 10):
                recent = history.tail(window)

                row[f"recent_points_for_{window}"] = (
                    recent["points_for"].mean()
                    if not recent.empty
                    else float("nan")
                )

                row[f"recent_points_against_{window}"] = (
                    recent["points_against"].mean()
                    if not recent.empty
                    else float("nan")
                )

                row[f"recent_games_used_{window}"] = len(
                    recent
                )

            rows.append(row)

    upcoming_form = pd.DataFrame(rows)

    return (
        pd.concat(
            [recent_form, upcoming_form],
            ignore_index=True,
        )
        .sort_values(
            ["match_date", "fixture_id", "team_id"]
        )
        .reset_index(drop=True)
    )


def build_strength_multipliers(
    connection: sqlite3.Connection,
    form_window: int = DEFAULT_FORM_WINDOW,
    league_window: int = DEFAULT_LEAGUE_WINDOW,
    prior_games: int = DEFAULT_PRIOR_GAMES,
    iterations: int = DEFAULT_ITERATIONS,
    curve_cap_start: float = DEFAULT_CURVE_CAP_START,
    curve_max_edit: float = DEFAULT_CURVE_MAX_EDIT,
    curve_learning_rate: float = DEFAULT_CURVE_LEARNING_RATE,
) -> pd.DataFrame:
    """Build opponent-adjusted attack and defence multipliers."""
    if form_window <= 0:
        raise ValueError("Form window must be positive.")

    if league_window <= 0:
        raise ValueError("League window must be positive.")

    if prior_games <= 0:
        raise ValueError("Prior games must be positive.")

    if iterations <= 0:
        raise ValueError("Iterations must be positive.")

    if curve_cap_start <= 0:
        raise ValueError("Curve cap start must be positive.")

    if curve_max_edit <= 0:
        raise ValueError("Curve maximum edit must be positive.")

    if curve_learning_rate <= 0:
        raise ValueError("Curve learning rate must be positive.")

    recent_form = load_recent_form(connection=connection)

    recent_form = add_upcoming_fixture_rows(
        connection=connection,
        recent_form=recent_form,
    )

    recent_form = add_league_average(
        recent_form=recent_form,
        league_window=league_window,
    )

    recent_form = add_opponent_recent_form(
        recent_form=recent_form,
        form_window=form_window,
    )

    strength = add_raw_multipliers(
        recent_form=recent_form,
        form_window=form_window,
        prior_games=prior_games,
    )

    return iterate_strength_multipliers(
        strength=strength,
        form_window=form_window,
        prior_games=prior_games,
        iterations=iterations,
    )


def rebuild_strength_multipliers(
    connection: sqlite3.Connection,
    form_window: int = DEFAULT_FORM_WINDOW,
    league_window: int = DEFAULT_LEAGUE_WINDOW,
    prior_games: int = DEFAULT_PRIOR_GAMES,
    iterations: int = DEFAULT_ITERATIONS,
    curve_cap_start: float = DEFAULT_CURVE_CAP_START,
    curve_max_edit: float = DEFAULT_CURVE_MAX_EDIT,
    curve_learning_rate: float = DEFAULT_CURVE_LEARNING_RATE,
) -> int:
    """Build and persist all available strength multipliers."""
    strength_multipliers = build_strength_multipliers(
        connection=connection,
        form_window=form_window,
        league_window=league_window,
        prior_games=prior_games,
        iterations=iterations,
        curve_cap_start=curve_cap_start,
        curve_max_edit=curve_max_edit,
        curve_learning_rate=curve_learning_rate,
    )

    return upsert_strength_multipliers(
        connection=connection,
        strength_multipliers=strength_multipliers,
    )