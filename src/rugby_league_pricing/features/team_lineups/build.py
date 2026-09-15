"""Build player-adjusted strength multipliers from team-news lineups."""

from __future__ import annotations

import sqlite3

import pandas as pd

from rugby_league_pricing.features.strength_multipliers.blended_final import (
    PlayerBlendModel,
    build_final_strength_multipliers,
    predict_selection_adjustments,
)
from rugby_league_pricing.features.team_lineups.adjustment_upsert import (
    upsert_team_selection_adjustments,
)
from rugby_league_pricing.features.team_lineups.strength import (
    build_team_lineup_strength,
)


MODEL_VERSION = "player_blend_v1"


def _load_fixture_teams(
    connection: sqlite3.Connection,
    fixture_id: str,
) -> pd.DataFrame:
    """Return the two team rows required for player adjustment."""
    fixture = pd.read_sql_query(
        """
        SELECT
            fixture_id,
            home_team_id,
            away_team_id
        FROM fixtures
        WHERE fixture_id = ?
        """,
        connection,
        params=(fixture_id,),
    )

    if fixture.empty:
        raise ValueError(
            f"Fixture not found: {fixture_id}"
        )

    row = fixture.iloc[0]

    return pd.DataFrame(
        [
            {
                "fixture_id": fixture_id,
                "team_id": int(row["home_team_id"]),
                "opponent_id": int(row["away_team_id"]),
                "is_home": 1,
            },
            {
                "fixture_id": fixture_id,
                "team_id": int(row["away_team_id"]),
                "opponent_id": int(row["home_team_id"]),
                "is_home": 0,
            },
        ]
    )


def _load_baseline_strength(
    connection: sqlite3.Connection,
    fixture_id: str,
) -> pd.DataFrame:
    """Load the form-only baseline strength multipliers."""
    baseline = pd.read_sql_query(
        """
        SELECT
            fixture_id,
            team_id,
            opponent_id,
            is_home,
            match_date,
            season,
            version_type,
            league_average_points,
            raw_attack_multiplier,
            raw_defence_multiplier,
            attack_multiplier,
            defence_multiplier,
            scaled_attack_multiplier,
            scaled_defence_multiplier
        FROM strength_multipliers
        WHERE fixture_id = ?
          AND version_type = 'baseline'
        ORDER BY team_id
        """,
        connection,
        params=(fixture_id,),
    )

    if len(baseline) != 2:
        raise ValueError(
            f"Expected 2 baseline strength rows for {fixture_id}; "
            f"found {len(baseline)}"
        )

    return baseline


def _build_fixture_lineup_strength(
    connection: sqlite3.Connection,
    fixture_id: str,
    version_type: str,
) -> pd.DataFrame:
    """Build player-strength features for both teams."""
    teams = _load_fixture_teams(
        connection,
        fixture_id,
    )

    rows = []

    for team in teams.itertuples(index=False):
        strength = build_team_lineup_strength(
            connection=connection,
            fixture_id=fixture_id,
            team_id=int(team.team_id),
            version_type=version_type,
        )

        strength["opponent_id"] = int(
            team.opponent_id
        )
        strength["is_home"] = int(
            team.is_home
        )

        rows.append(strength)

    return pd.concat(
        rows,
        ignore_index=True,
    )


def _build_adjustment_rows(
    lineup_strength: pd.DataFrame,
    predictions: pd.DataFrame,
    version_type: str,
) -> pd.DataFrame:
    """Prepare rows for team_selection_adjustments."""
    prediction_cols = [
        "fixture_id",
        "team_id",
        "player_log_adjustment",
        "score_adjustment_factor",
    ]

    result = lineup_strength.merge(
        predictions[prediction_cols],
        on=["fixture_id", "team_id"],
        how="left",
        validate="one_to_one",
    )

    result["version_type"] = version_type
    result["model_version"] = MODEL_VERSION

    return result


def build_player_adjusted_strength(
    connection: sqlite3.Connection,
    fixture_id: str,
    version_type: str,
    blend_model: PlayerBlendModel,
) -> pd.DataFrame:
    """
    Build player-adjusted strength multipliers for one fixture.

    Flow:
        baseline strength
        -> lineup strength
        -> Ridge player adjustment
        -> audit adjustment table
        -> final versioned strength multipliers
    """
    baseline = _load_baseline_strength(
        connection,
        fixture_id,
    )

    lineup_strength = (
        _build_fixture_lineup_strength(
            connection=connection,
            fixture_id=fixture_id,
            version_type=version_type,
        )
    )

    predictions = (
        predict_selection_adjustments(
            lineup_strength=lineup_strength,
            blend_model=blend_model,
        )
    )

    adjustment_rows = (
        _build_adjustment_rows(
            lineup_strength=lineup_strength,
            predictions=predictions,
            version_type=version_type,
        )
    )

    upsert_team_selection_adjustments(
        connection=connection,
        adjustments=adjustment_rows,
    )

    final_strength = (
        build_final_strength_multipliers(
            baseline=baseline,
            adjustments=predictions,
            version_type=version_type,
        )
    )

    return final_strength