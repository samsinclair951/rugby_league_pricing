"""Train and persist player-blend model snapshots."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from rugby_league_pricing.features.strength_multipliers.blended_final import (
    DEFAULT_RIDGE_ALPHA,
    attach_opponent_features,
    fit_player_blend_model,
)
from rugby_league_pricing.features.strength_multipliers.model_store import (
    save_player_blend_model,
)


DATABASE_PATH = Path(
    "/workspaces/rugby_league_pricing/data/rugby_league_pricing.db"
)

MODEL_PREFIX = "player_blend"


def load_training_frame(
    connection: sqlite3.Connection,
    *,
    through_date: pd.Timestamp,
) -> pd.DataFrame:
    """
    Load historical player-selection features and baseline expected points.

    IMPORTANT:
    This assumes team_selection_adjustments contains historical feature rows
    built using only pre-match player ratings / prior lineup history.
    """
    frame = pd.read_sql_query(
        """
        SELECT
            tsa.fixture_id,
            tsa.team_id,
            tsa.opponent_id,
            tsa.is_home,

            f.match_date,

            tsa.player_strength_signal,
            tsa.top5_strength_on_field,
            tsa.props_8_10_strength,
            tsa.middle_pack_8_10_11_12_13_strength,
            tsa.halves_6_7_strength,
            tsa.spine_1_6_7_9_strength,
            tsa.hooker_9_strength,
            tsa.stand_off_6_strength,
            tsa.scrum_half_7_strength,

            tsa.missing_core_overall_sum,
            tsa.missing_core_top3_sum,
            tsa.missing_props_8_10_sum,
            tsa.missing_middle_pack_8_10_11_12_13_sum,
            tsa.missing_halves_6_7_sum,
            tsa.missing_spine_1_6_7_9_sum,
            tsa.missing_hooker_9_sum,
            tsa.missing_stand_off_6_sum,
            tsa.missing_scrum_half_7_sum,

            sm.scaled_attack_multiplier,
            es.expected_home_score,
            es.expected_away_score,

            CASE
                WHEN tsa.is_home = 1
                    THEN es.expected_home_score
                ELSE es.expected_away_score
            END AS baseline_expected_points,

            CASE
                WHEN tsa.is_home = 1
                    THEN r.home_score
                ELSE r.away_score
            END AS points_for

        FROM team_selection_adjustments tsa

        JOIN fixtures f
            ON f.fixture_id = tsa.fixture_id

        JOIN strength_multipliers sm
            ON sm.fixture_id = tsa.fixture_id
           AND sm.team_id = tsa.team_id
           AND sm.version_type = 'baseline'

        JOIN expected_scores es
            ON es.fixture_id = tsa.fixture_id

        JOIN results r
            ON r.fixture_id = tsa.fixture_id

        WHERE f.match_date <= ?
          AND tsa.version_type = 'confirmed_line_up'

        ORDER BY
            f.match_date,
            tsa.fixture_id,
            tsa.team_id
        """,
        connection,
        params=(
            pd.Timestamp(through_date).strftime("%Y-%m-%d"),
        ),
        parse_dates=["match_date"],
    )

    if frame.empty:
        raise ValueError(
            f"No player-blend training data found through {through_date.date()}"
        )

    return frame


def build_model_version(
    trained_through_date: pd.Timestamp,
) -> str:
    """Create deterministic model version."""
    return (
        f"{MODEL_PREFIX}_"
        f"{trained_through_date.strftime('%Y_%m_%d')}"
    )


def train_and_store_snapshot(
    connection: sqlite3.Connection,
    *,
    trained_through_date: pd.Timestamp,
    ridge_alpha: float = DEFAULT_RIDGE_ALPHA,
) -> str:
    """Train and persist one model snapshot."""
    frame = load_training_frame(
        connection,
        through_date=trained_through_date,
    )

    # The model expects opponent features too.
    frame = attach_opponent_features(frame)

    blend_model = fit_player_blend_model(
        frame,
        ridge_alpha=ridge_alpha,
    )

    model_version = build_model_version(
        trained_through_date
    )

    save_player_blend_model(
        connection,
        model_version=model_version,
        trained_through_date=trained_through_date,
        ridge_alpha=ridge_alpha,
        blend_model=blend_model,
    )

    print(
        f"Saved {model_version} "
        f"using {len(frame):,} team-match rows"
    )

    return model_version


def completed_week_cutoffs(
    connection: sqlite3.Connection,
    *,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
) -> list[pd.Timestamp]:
    """
    Return weekly model cutoffs based on completed fixture dates.

    Each cutoff is the final completed match date in an ISO week.
    """
    fixtures = pd.read_sql_query(
        """
        SELECT DISTINCT
            f.match_date
        FROM fixtures f
        JOIN results r
            ON r.fixture_id = f.fixture_id
        ORDER BY f.match_date
        """,
        connection,
        parse_dates=["match_date"],
    )

    if fixtures.empty:
        return []

    fixtures["match_date"] = (
        pd.to_datetime(fixtures["match_date"])
        .dt.normalize()
    )

    if start_date is not None:
        fixtures = fixtures[
            fixtures["match_date"]
            >= pd.Timestamp(start_date)
        ]

    if end_date is not None:
        fixtures = fixtures[
            fixtures["match_date"]
            <= pd.Timestamp(end_date)
        ]

    iso = fixtures["match_date"].dt.isocalendar()

    fixtures["iso_year"] = iso.year
    fixtures["iso_week"] = iso.week

    cutoffs = (
        fixtures
        .groupby(
            ["iso_year", "iso_week"],
            as_index=False,
        )["match_date"]
        .max()
        .sort_values("match_date")
    )

    return cutoffs["match_date"].tolist()


def rebuild_weekly_models(
    connection: sqlite3.Connection,
    *,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
    ridge_alpha: float = DEFAULT_RIDGE_ALPHA,
) -> None:
    """Rebuild all weekly blend-model snapshots."""
    cutoffs = completed_week_cutoffs(
        connection,
        start_date=start_date,
        end_date=end_date,
    )

    if not cutoffs:
        raise ValueError(
            "No completed weekly fixture cutoffs found."
        )

    for cutoff in cutoffs:
        try:
            train_and_store_snapshot(
                connection,
                trained_through_date=cutoff,
                ridge_alpha=ridge_alpha,
            )

        except ValueError as exc:
            # Early seasons may not have enough historical
            # player-selection data to fit a useful model.
            print(
                f"Skipping {cutoff.date()}: {exc}"
            )


def latest_completed_fixture_date(
    connection: sqlite3.Connection,
) -> pd.Timestamp:
    """Return the latest completed fixture date."""
    row = pd.read_sql_query(
        """
        SELECT
            MAX(f.match_date) AS match_date
        FROM fixtures f
        JOIN results r
            ON r.fixture_id = f.fixture_id
        """,
        connection,
        parse_dates=["match_date"],
    )

    if (
        row.empty
        or pd.isna(row.iloc[0]["match_date"])
    ):
        raise ValueError(
            "No completed fixture dates found."
        )

    return pd.Timestamp(
        row.iloc[0]["match_date"]
    ).normalize()


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--weekly",
        action="store_true",
        help="Rebuild historical weekly model snapshots.",
    )

    parser.add_argument(
        "--through-date",
        type=str,
        default=None,
        help="Train a single snapshot through YYYY-MM-DD.",
    )

    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date for weekly rebuild.",
    )

    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date for weekly rebuild.",
    )

    parser.add_argument(
        "--ridge-alpha",
        type=float,
        default=DEFAULT_RIDGE_ALPHA,
    )

    args = parser.parse_args()

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DATABASE_PATH}"
        )

    with sqlite3.connect(DATABASE_PATH) as connection:
        if args.weekly:
            rebuild_weekly_models(
                connection,
                start_date=(
                    pd.Timestamp(args.start_date)
                    if args.start_date
                    else None
                ),
                end_date=(
                    pd.Timestamp(args.end_date)
                    if args.end_date
                    else None
                ),
                ridge_alpha=args.ridge_alpha,
            )

            return

        through_date = (
            pd.Timestamp(args.through_date)
            if args.through_date
            else latest_completed_fixture_date(
                connection
            )
        )

        train_and_store_snapshot(
            connection,
            trained_through_date=through_date,
            ridge_alpha=args.ridge_alpha,
        )


if __name__ == "__main__":
    main()