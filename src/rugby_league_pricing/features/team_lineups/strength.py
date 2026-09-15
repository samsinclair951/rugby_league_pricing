"""Build player-strength features from expected or confirmed team lineups."""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd


REFERENCE_WINDOW = 8
CORE_MIN_APPEARANCES = 3


KEY_POSITION_GROUPS: dict[str, set[int]] = {
    "props_8_10": {8, 10},
    "middle_pack_8_10_11_12_13": {8, 10, 11, 12, 13},
    "halves_6_7": {6, 7},
    "spine_1_6_7_9": {1, 6, 7, 9},
    "combo_1_7": {1, 7},
    "combo_1_6": {1, 6},
    "hooker_9": {9},
    "stand_off_6": {6},
    "scrum_half_7": {7},
}


def _weighted_sum(
    values: pd.Series,
    weights: pd.Series | None,
) -> float:
    """Return a reliability-weighted sum."""
    if values.empty:
        return 0.0

    if weights is None:
        return float(values.sum())

    if float(weights.sum()) <= 0:
        return float(values.sum())

    return float(
        (values * weights).sum()
    )


def _load_fixture(
    connection: sqlite3.Connection,
    fixture_id: str,
) -> pd.Series:
    """Load fixture metadata."""
    fixture = pd.read_sql_query(
        """
        SELECT
            fixture_id,
            match_date,
            season,
            home_team_id,
            away_team_id
        FROM fixtures
        WHERE fixture_id = ?
        """,
        connection,
        params=(fixture_id,),
        parse_dates=["match_date"],
    )

    if fixture.empty:
        raise ValueError(
            f"Fixture not found: {fixture_id}"
        )

    return fixture.iloc[0]


def _load_lineup(
    connection: sqlite3.Connection,
    fixture_id: str,
    team_id: int,
    version_type: str,
) -> pd.DataFrame:
    """
    Load one expected/confirmed lineup.

    Expected lineups come from expected_team_lineups.

    Historical confirmed lineups fall back to actual teamsheets.
    """

    lineup = pd.read_sql_query(
        """
        SELECT
            fixture_id,
            team_id,
            player_id,
            player_name,
            position_id,
            version_type
        FROM expected_team_lineups
        WHERE fixture_id = ?
          AND team_id = ?
          AND version_type = ?
        ORDER BY position_id, player_name
        """,
        connection,
        params=(
            fixture_id,
            team_id,
            version_type,
        ),
    )

    # Historical confirmed teams are stored in teamsheets rather
    # than expected_team_lineups.
    if lineup.empty and version_type == "confirmed_line_up":
        lineup = pd.read_sql_query(
            """
            SELECT
                fixture_id,
                team_id,
                CAST(player_id AS TEXT) AS player_id,
                CAST(player_id AS TEXT) AS player_name,
                NULL AS position_id,
                'confirmed_line_up' AS version_type
            FROM teamsheets
            WHERE fixture_id = ?
              AND team_id = ?
            ORDER BY lineup_order
            """,
            connection,
            params=(
                fixture_id,
                team_id,
            ),
        )

    if lineup.empty:
        raise ValueError(
            "No lineup found for "
            f"fixture={fixture_id}, "
            f"team={team_id}, "
            f"version={version_type}"
        )

    lineup["player_id"] = (
        lineup["player_id"].astype(str)
    )

    lineup["position_id"] = pd.to_numeric(
        lineup["position_id"],
        errors="coerce",
    )

    return lineup

def _load_latest_player_ratings(
    connection: sqlite3.Connection,
    team_id: int,
    before_date: pd.Timestamp,
) -> pd.DataFrame:
    """
    Load the latest available pre-match rating for each player.

    No rating from the fixture being priced or any later fixture is used.
    """
    ratings = pd.read_sql_query(
        """
        WITH ranked AS (
            SELECT
                pr.player_id,
                pr.player_name,
                pr.team_id,
                pr.position_id,
                pr.attack_rating,
                pr.defence_rating,
                pr.overall_rating,
                pr.reliability,
                f.match_date,

                ROW_NUMBER() OVER (
                    PARTITION BY pr.player_id
                    ORDER BY
                        f.match_date DESC,
                        pr.fixture_id DESC
                ) AS rating_rank

            FROM player_ratings pr

            JOIN fixtures f
                ON f.fixture_id = pr.fixture_id

            WHERE pr.team_id = ?
              AND f.match_date < ?
        )

        SELECT
            player_id,
            player_name,
            team_id,
            position_id,
            attack_rating,
            defence_rating,
            overall_rating,
            reliability,
            match_date
        FROM ranked
        WHERE rating_rank = 1
        """,
        connection,
        params=(
            team_id,
            before_date.strftime("%Y-%m-%d"),
        ),
        parse_dates=["match_date"],
    )

    ratings["player_id"] = (
        ratings["player_id"].astype(str)
    )

    ratings["position_id"] = pd.to_numeric(
        ratings["position_id"],
        errors="coerce",
    )

    return ratings


def _load_recent_selections(
    connection: sqlite3.Connection,
    team_id: int,
    before_date: pd.Timestamp,
    window: int = REFERENCE_WINDOW,
) -> pd.DataFrame:
    """Load the team's previous N actual selections."""
    return pd.read_sql_query(
        """
        WITH recent_fixtures AS (
            SELECT DISTINCT
                ts.fixture_id,
                f.match_date

            FROM teamsheets ts

            JOIN fixtures f
                ON f.fixture_id = ts.fixture_id

            WHERE ts.team_id = ?
              AND f.match_date < ?

            ORDER BY f.match_date DESC
            LIMIT ?
        )

        SELECT
            ts.fixture_id,
            ts.player_id,
            ts.position,
            ts.is_starting,
            rf.match_date

        FROM teamsheets ts

        JOIN recent_fixtures rf
            ON rf.fixture_id = ts.fixture_id

        WHERE ts.team_id = ?

        ORDER BY
            rf.match_date DESC,
            ts.fixture_id,
            ts.lineup_order
        """,
        connection,
        params=(
            team_id,
            before_date.strftime("%Y-%m-%d"),
            window,
            team_id,
        ),
        parse_dates=["match_date"],
    )


def _build_core_player_ids(
    recent_selections: pd.DataFrame,
) -> set[str]:
    """
    Define the rolling core squad.

    A player is core if they appeared in at least CORE_MIN_APPEARANCES
    of the previous REFERENCE_WINDOW matches.
    """
    if recent_selections.empty:
        return set()

    appearances = (
        recent_selections[
            ["fixture_id", "player_id"]
        ]
        .drop_duplicates()
        .groupby("player_id")
        .size()
    )

    return set(
        appearances[
            appearances >= CORE_MIN_APPEARANCES
        ].index.astype(str)
    )


def _build_reference_player_ids(
    recent_selections: pd.DataFrame,
) -> set[str]:
    """
    Build a simple full-strength reference pool from recent selections.

    For now, use the rolling core definition already used by the notebook:
    players selected in at least CORE_MIN_APPEARANCES of the previous
    REFERENCE_WINDOW fixtures.
    """
    return _build_core_player_ids(recent_selections)


def _summarise_reference_strength(
    ratings: pd.DataFrame,
    reference_player_ids: set[str],
) -> dict[str, float]:
    """Summarise attack/defence strength for the rolling reference squad."""
    reference = ratings[
        ratings["player_id"].isin(reference_player_ids)
    ].copy()

    if reference.empty:
        return {
            "reference_attack_strength": 0.0,
            "reference_defence_strength": 0.0,
        }

    reliability = (
        reference["reliability"]
        .fillna(0.0)
        .clip(lower=0.0, upper=1.0)
    )

    return {
        "reference_attack_strength": _weighted_sum(
            reference["attack_rating"].fillna(0.0),
            reliability,
        ),
        "reference_defence_strength": _weighted_sum(
            reference["defence_rating"].fillna(0.0),
            reliability,
        ),
    }


def _summarise_players(
    ratings: pd.DataFrame,
) -> dict[str, float]:
    """Summarise ratings for one player group."""
    result: dict[str, float] = {
        "player_attack_signal": 0.0,
        "player_defence_signal": 0.0,
        "player_strength_signal": 0.0,
        "player_reliability_mean": 0.0,
        "top5_strength_on_field": 0.0,
    }

    for group_name in KEY_POSITION_GROUPS:
        result[f"{group_name}_strength"] = 0.0

    if ratings.empty:
        return result

    reliability = (
        ratings["reliability"]
        .fillna(0.0)
        .clip(lower=0.0, upper=1.0)
    )

    attack = _weighted_sum(
        ratings["attack_rating"].fillna(0.0),
        reliability,
    )

    defence = _weighted_sum(
        ratings["defence_rating"].fillna(0.0),
        reliability,
    )

    result["player_attack_signal"] = attack
    result["player_defence_signal"] = defence
    result["player_strength_signal"] = (
        attack + defence
    )

    result["player_reliability_mean"] = float(
        reliability.mean()
    )

    top5 = ratings.nlargest(
        5,
        "overall_rating",
    )

    result["top5_strength_on_field"] = (
        _weighted_sum(
            top5["overall_rating"].fillna(0.0),
            top5["reliability"]
            .fillna(0.0)
            .clip(lower=0.0, upper=1.0),
        )
    )

    for group_name, positions in (
        KEY_POSITION_GROUPS.items()
    ):
        group = ratings[
            ratings["position_id"].isin(
                positions
            )
        ]

        result[f"{group_name}_strength"] = (
            _weighted_sum(
                group[
                    "overall_rating"
                ].fillna(0.0),
                group["reliability"]
                .fillna(0.0)
                .clip(
                    lower=0.0,
                    upper=1.0,
                ),
            )
        )

    return result


def _summarise_missing_core(
    ratings: pd.DataFrame,
    core_player_ids: set[str],
    selected_player_ids: set[str],
) -> dict[str, float]:
    """Calculate missing-core player signals."""
    missing_ids = (
        core_player_ids
        - selected_player_ids
    )

    result: dict[str, float] = {
        "core_player_pool_size": float(
            len(core_player_ids)
        ),
        "missing_core_count": float(
            len(missing_ids)
        ),
        "missing_core_overall_sum": 0.0,
        "missing_core_top3_sum": 0.0,
    }

    for group_name in KEY_POSITION_GROUPS:
        result[
            f"missing_{group_name}_sum"
        ] = 0.0

    if not missing_ids:
        return result

    missing = ratings[
        ratings["player_id"].isin(
            missing_ids
        )
    ].copy()

    if missing.empty:
        return result

    # Only positive historical contribution counts
    # as a meaningful absence.
    missing["positive_rating"] = (
        missing["overall_rating"]
        .fillna(0.0)
        .clip(lower=0.0)
    )

    result["missing_core_overall_sum"] = float(
        missing["positive_rating"].sum()
    )

    result["missing_core_top3_sum"] = float(
        missing["positive_rating"]
        .nlargest(3)
        .sum()
    )

    for group_name, positions in (
        KEY_POSITION_GROUPS.items()
    ):
        result[
            f"missing_{group_name}_sum"
        ] = float(
            missing.loc[
                missing["position_id"].isin(
                    positions
                ),
                "positive_rating",
            ].sum()
        )

    return result


def build_team_lineup_strength(
    connection: sqlite3.Connection,
    fixture_id: str,
    team_id: int,
    version_type: str,
) -> pd.DataFrame:
    """
    Build player-strength features for one team/fixture/version.

    These fields are designed to mirror the successful notebook
    player-selection features.
    """
    fixture = _load_fixture(
        connection=connection,
        fixture_id=fixture_id,
    )

    match_date = pd.Timestamp(
        fixture["match_date"]
    )

    lineup = _load_lineup(
        connection=connection,
        fixture_id=fixture_id,
        team_id=team_id,
        version_type=version_type,
    )

    ratings = _load_latest_player_ratings(
        connection=connection,
        team_id=team_id,
        before_date=match_date,
    )

    selected_ids = set(
        lineup["player_id"]
        .astype(str)
        .tolist()
    )

    selected_ratings = ratings[
        ratings["player_id"].isin(
            selected_ids
        )
    ].copy()

    recent_selections = (
        _load_recent_selections(
            connection=connection,
            team_id=team_id,
            before_date=match_date,
        )
    )

    core_player_ids = (
        _build_core_player_ids(
            recent_selections
        )
    )

    reference_player_ids = _build_reference_player_ids(
        recent_selections
    )

    reference_strength = _summarise_reference_strength(
        ratings=ratings,
        reference_player_ids=reference_player_ids,
    )

    strength = _summarise_players(
        selected_ratings
    )

    selected_attack_strength = strength[
        "player_attack_signal"
    ]
    selected_defence_strength = strength[
        "player_defence_signal"
    ]

    attack_selection_gap = (
        selected_attack_strength
        - reference_strength[
            "reference_attack_strength"
        ]
    )

    defence_selection_gap = (
        selected_defence_strength
        - reference_strength[
            "reference_defence_strength"
        ]
    )
    missing = _summarise_missing_core(
        ratings=ratings,
        core_player_ids=core_player_ids,
        selected_player_ids=selected_ids,
    )

    rated_player_count = len(
        selected_ratings
    )

    row = {
        "fixture_id": fixture_id,
        "team_id": int(team_id),
        "version_type": version_type,
        "match_date": match_date,
        "season": int(fixture["season"]),
        "selected_player_count": int(
            len(selected_ids)
        ),
        "rated_player_count": int(
            rated_player_count
        ),
        "reference_attack_strength": reference_strength[
            "reference_attack_strength"
        ],
        "selected_attack_strength": selected_attack_strength,
        "attack_selection_gap": attack_selection_gap,

        "reference_defence_strength": reference_strength[
            "reference_defence_strength"
        ],
        "selected_defence_strength": selected_defence_strength,
        "defence_selection_gap": defence_selection_gap,
        **strength,
        **missing,
    }

    return pd.DataFrame(
        [row]
    )