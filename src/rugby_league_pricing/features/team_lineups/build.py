"""Build player-adjusted strength multipliers from expected-team lineups.

This module is the bridge between the manual team-news input (the
expected_team_lineups table) and the strength_multipliers table.

Workflow
--------
1. A user inputs an expected or confirmed lineup for an upcoming fixture into
   the expected_team_lineups table, tagged with a version_type such as
   'preview_expected_line_up' or 'confirmed_line_up'.
2. This module reads that lineup, looks up each player's ratings from the
   player_ratings table, and computes a disruption-based adjustment factor.
3. The baseline strength multipliers for the fixture are then scaled by those
   factors and written back to strength_multipliers under the same version_type.

The adjustment logic is intentionally simple and transparent:
  - Sum the overall ratings of players who are ABSENT relative to the baseline
    core squad (i.e. they appear in historical form but not in the expected lineup).
  - Apply a small multiplicative penalty to the baseline attack multiplier.
  - Apply the inverse penalty to the baseline defence multiplier.
  - Clamp adjustments so a single absence cannot move a multiplier by more than
    MAX_ADJUSTMENT_FACTOR from the baseline.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from rugby_league_pricing.features.strength_multipliers.upsert import (
    upsert_strength_multipliers,
)

from .upsert import upsert_expected_team_lineups

MAX_ADJUSTMENT_FACTOR = 0.20  # max ±20% shift per team per fixture
ABSENCE_SENSITIVITY = 0.025   # rating points per 1.0 of missing overall_rating

VALID_VERSION_TYPES = {
    "pre_preview_expected_line_up",
    "preview_expected_line_up",
    "confirmed_line_up",
}


def load_lineup_input(path: str) -> pd.DataFrame:
    """Load a CSV or JSON lineup input file.

    Expected columns:
        fixture_id, team_id, player_id, player_name, position_id,
        version_type, notes (optional)

    A sample CSV is provided at:
        data/team_lineups/sample_expected_lineup.csv
    """
    import pathlib

    p = pathlib.Path(path)
    if p.suffix == ".csv":
        df = pd.read_csv(p)
    elif p.suffix == ".json":
        df = pd.read_json(p)
    else:
        raise ValueError(f"Unsupported file format: {p.suffix}. Use .csv or .json")

    df["fixture_id"] = df["fixture_id"].astype(str)
    df["team_id"] = df["team_id"].astype(str)
    df["player_id"] = df["player_id"].astype(str)
    df["player_name"] = df["player_name"].astype(str)
    df["position_id"] = pd.to_numeric(df["position_id"], errors="coerce")

    if "notes" not in df.columns:
        df["notes"] = None

    invalid_types = set(df["version_type"].unique()) - VALID_VERSION_TYPES
    if invalid_types:
        raise ValueError(
            f"Invalid version_type values: {invalid_types}. "
            f"Must be one of: {VALID_VERSION_TYPES}"
        )

    return df


def _load_baseline_multipliers(
    connection: sqlite3.Connection,
    fixture_ids: list[str],
) -> pd.DataFrame:
    """Load the baseline form-only multipliers for the given fixtures."""
    placeholders = ", ".join("?" * len(fixture_ids))
    return pd.read_sql_query(
        f"""
        SELECT
            fixture_id,
            team_id,
            opponent_id,
            is_home,
            match_date,
            season,
            league_average_points,
            raw_attack_multiplier,
            raw_defence_multiplier,
            attack_multiplier,
            defence_multiplier,
            scaled_attack_multiplier,
            scaled_defence_multiplier
        FROM strength_multipliers
        WHERE version_type = 'baseline'
          AND fixture_id IN ({placeholders})
        ORDER BY fixture_id, team_id
        """,
        connection,
        params=fixture_ids,
        parse_dates=["match_date"],
    )


def _load_player_ratings(
    connection: sqlite3.Connection,
    fixture_ids: list[str],
) -> pd.DataFrame:
    """Load historical player ratings for context."""
    placeholders = ", ".join("?" * len(fixture_ids))
    return pd.read_sql_query(
        f"""
        SELECT
            player_id,
            team_id,
            overall_rating,
            attack_rating,
            defence_rating,
            reliability
        FROM player_ratings
        WHERE fixture_id IN ({placeholders})
        """,
        connection,
        params=fixture_ids,
    )


def _compute_adjustment_factor(
    expected_lineup: pd.DataFrame,
    player_ratings: pd.DataFrame,
    team_id: str,
) -> float:
    """Compute a [0, MAX_ADJUSTMENT_FACTOR] penalty for missing players.

    Compares the player IDs in the expected lineup against the most-rated
    players historically seen for this team, and penalises absences by their
    contribution to the team's overall_rating.

    Returns a factor in [0, MAX_ADJUSTMENT_FACTOR] where 0 means full-strength
    and MAX_ADJUSTMENT_FACTOR means maximum disruption.
    """
    team_ratings = player_ratings[player_ratings["team_id"] == str(team_id)].copy()
    if team_ratings.empty:
        return 0.0

    expected_ids = set(expected_lineup["player_id"])
    missing = team_ratings[~team_ratings["player_id"].isin(expected_ids)]

    # Only penalise missing players with positive overall ratings.
    missing_value = missing["overall_rating"].clip(lower=0).sum()

    raw_penalty = missing_value * ABSENCE_SENSITIVITY
    return float(np.clip(raw_penalty, 0.0, MAX_ADJUSTMENT_FACTOR))


def build_lineup_adjusted_multipliers(
    connection: sqlite3.Connection,
    lineups: pd.DataFrame,
    version_type: str,
) -> pd.DataFrame:
    """Compute player-adjusted strength multipliers from an expected lineup.

    Parameters
    ----------
    connection:
        Open SQLite connection.
    lineups:
        Expected lineup rows as loaded by load_lineup_input().
    version_type:
        The version_type to assign to the output rows.
    """
    if version_type not in VALID_VERSION_TYPES:
        raise ValueError(
            f"version_type must be one of {VALID_VERSION_TYPES}, got {version_type!r}"
        )

    fixture_ids = lineups["fixture_id"].unique().tolist()
    baselines = _load_baseline_multipliers(connection, fixture_ids)

    if baselines.empty:
        raise ValueError(
            "No baseline strength multipliers found for the provided fixture IDs. "
            "Run rebuild_strength_multipliers first."
        )

    # Use ratings from the previous 40 fixtures worth of data as context.
    historical_fixture_ids = pd.read_sql_query(
        """
        SELECT DISTINCT fixture_id
        FROM player_ratings
        ORDER BY fixture_id DESC
        LIMIT 40
        """,
        connection,
    )["fixture_id"].tolist()

    player_ratings = _load_player_ratings(connection, historical_fixture_ids)

    rows = []
    for _, baseline_row in baselines.iterrows():
        fixture_id = str(baseline_row["fixture_id"])
        team_id = str(baseline_row["team_id"])

        team_lineup = lineups[
            (lineups["fixture_id"] == fixture_id) & (lineups["team_id"] == team_id)
        ]

        penalty = _compute_adjustment_factor(
            expected_lineup=team_lineup,
            player_ratings=player_ratings,
            team_id=team_id,
        )

        attack_factor = 1.0 - penalty
        defence_factor = 1.0 + penalty

        row = baseline_row.to_dict()
        row["version_type"] = version_type
        row["scaled_attack_multiplier"] = (
            float(baseline_row["scaled_attack_multiplier"] or 0) * attack_factor
        )
        row["scaled_defence_multiplier"] = (
            float(baseline_row["scaled_defence_multiplier"] or 0) * defence_factor
        )
        rows.append(row)

    result = pd.DataFrame(rows)
    result["team_id"] = result["team_id"].astype(int)
    result["opponent_id"] = result["opponent_id"].astype(int)

    return result


def ingest_lineup_file(
    connection: sqlite3.Connection,
    path: str,
) -> tuple[int, int]:
    """Load a lineup file, store the raw rows, and produce adjusted multipliers.

    Returns
    -------
    (lineup_rows_saved, multiplier_rows_saved)
    """
    lineups = load_lineup_input(path)
    version_type = lineups["version_type"].iloc[0]

    lineup_rows = upsert_expected_team_lineups(
        connection=connection,
        lineups=lineups,
    )

    adjusted = build_lineup_adjusted_multipliers(
        connection=connection,
        lineups=lineups,
        version_type=version_type,
    )

    multiplier_rows = upsert_strength_multipliers(
        connection=connection,
        strength_multipliers=adjusted,
        version_type=version_type,
    )

    return lineup_rows, multiplier_rows
