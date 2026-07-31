from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pandas as pd

FUTURE_FIXTURES_QUERY = """
    SELECT
        f.fixture_id,
        f.match_date,
        f.home_team_id,
        f.away_team_id
    FROM fixtures AS f
    LEFT JOIN results AS r
        ON f.fixture_id = r.fixture_id
    WHERE
        DATE(f.match_date) >= DATE('now')
        AND (
            r.fixture_id IS NULL
            OR r.home_score IS NULL
            OR r.away_score IS NULL
        )
    ORDER BY
        f.match_date,
        f.fixture_id
"""


STRENGTH_MULTIPLIERS_QUERY = """
    SELECT
        fixture_id,
        team_id,
        match_date,
        scaled_attack_multiplier,
        scaled_defence_multiplier
    FROM strength_multipliers
    WHERE
        scaled_attack_multiplier IS NOT NULL
        AND scaled_defence_multiplier IS NOT NULL
    ORDER BY
        team_id,
        match_date,
        fixture_id
"""


RESULTS_QUERY = """
    SELECT
        f.fixture_id,
        f.match_date,
        r.home_score,
        r.away_score
    FROM fixtures AS f
    JOIN results AS r
        ON f.fixture_id = r.fixture_id
    WHERE
        r.home_score IS NOT NULL
        AND r.away_score IS NOT NULL
    ORDER BY
        f.match_date,
        f.fixture_id
"""


PREDICTION_COLUMNS = [
    "fixture_id",
    "prediction_date",
    "home_team_id",
    "away_team_id",
    "league_average_points",
    "home_scoring_factor",
    "away_scoring_factor",
    "home_attack_multiplier",
    "home_defence_multiplier",
    "away_attack_multiplier",
    "away_defence_multiplier",
    "expected_home_score",
    "expected_away_score",
]


def load_future_fixtures(
    connection: sqlite3.Connection,
) -> pd.DataFrame:
    """Load fixtures which do not yet have a completed result."""
    fixtures = pd.read_sql_query(
        FUTURE_FIXTURES_QUERY,
        connection,
    )

    if fixtures.empty:
        return fixtures

    fixtures["match_date"] = pd.to_datetime(
        fixtures["match_date"],
        errors="raise",
    )

    return fixtures


def load_strength_multipliers(
    connection: sqlite3.Connection,
) -> pd.DataFrame:
    """Load historical scaled team-strength multipliers."""
    strength = pd.read_sql_query(
        STRENGTH_MULTIPLIERS_QUERY,
        connection,
    )

    if strength.empty:
        raise ValueError("No scaled strength multipliers were found.")

    strength["match_date"] = pd.to_datetime(
        strength["match_date"],
        errors="raise",
    )

    return strength


def load_completed_results(
    connection: sqlite3.Connection,
) -> pd.DataFrame:
    """Load completed results used to calculate scoring factors."""
    results = pd.read_sql_query(
        RESULTS_QUERY,
        connection,
    )

    if results.empty:
        raise ValueError("No completed results were found.")

    results["match_date"] = pd.to_datetime(
        results["match_date"],
        errors="raise",
    )

    return results


def latest_team_strength(
    strength: pd.DataFrame,
    team_id: int,
    fixture_date: pd.Timestamp,
) -> pd.Series:
    """Return a team's latest strength before a fixture."""
    available = strength.loc[
        (strength["team_id"] == team_id) & (strength["match_date"] < fixture_date)
    ]

    if available.empty:
        raise ValueError(
            "No historical strength multiplier found for "
            f"team_id={team_id} before {fixture_date.date()}."
        )

    return available.iloc[-1]


def calculate_scoring_factors(
    results: pd.DataFrame,
    fixture_date: pd.Timestamp,
) -> tuple[float, float, float]:
    """
    Calculate league, home and away scoring factors before a fixture.

    League average points represents the average score per team.
    """
    historical = results.loc[results["match_date"] < fixture_date]

    if historical.empty:
        raise ValueError(f"No completed results exist before {fixture_date.date()}.")

    total_points = historical["home_score"].sum() + historical["away_score"].sum()

    league_average_points = float(total_points / (2 * len(historical)))

    if league_average_points <= 0:
        raise ValueError("League average points must be positive.")

    home_average_points = float(historical["home_score"].mean())

    away_average_points = float(historical["away_score"].mean())

    home_scoring_factor = home_average_points / league_average_points

    away_scoring_factor = away_average_points / league_average_points

    return (
        league_average_points,
        home_scoring_factor,
        away_scoring_factor,
    )


def build_expected_score_predictions(
    connection: sqlite3.Connection,
) -> pd.DataFrame:
    """Build expected scores for all future fixtures."""
    fixtures = load_future_fixtures(
        connection=connection,
    )

    if fixtures.empty:
        return pd.DataFrame(columns=PREDICTION_COLUMNS)

    strength = load_strength_multipliers(
        connection=connection,
    )

    results = load_completed_results(
        connection=connection,
    )

    predictions: list[dict[str, object]] = []

    for fixture in fixtures.itertuples(index=False):
        fixture_date = pd.Timestamp(fixture.match_date)

        home_strength = latest_team_strength(
            strength=strength,
            team_id=int(fixture.home_team_id),
            fixture_date=fixture_date,
        )

        away_strength = latest_team_strength(
            strength=strength,
            team_id=int(fixture.away_team_id),
            fixture_date=fixture_date,
        )

        (
            league_average_points,
            home_scoring_factor,
            away_scoring_factor,
        ) = calculate_scoring_factors(
            results=results,
            fixture_date=fixture_date,
        )

        home_attack_multiplier = float(home_strength["scaled_attack_multiplier"])

        home_defence_multiplier = float(home_strength["scaled_defence_multiplier"])

        away_attack_multiplier = float(away_strength["scaled_attack_multiplier"])

        away_defence_multiplier = float(away_strength["scaled_defence_multiplier"])

        expected_home_score = (
            league_average_points
            * home_scoring_factor
            * home_attack_multiplier
            * away_defence_multiplier
        )

        expected_away_score = (
            league_average_points
            * away_scoring_factor
            * away_attack_multiplier
            * home_defence_multiplier
        )

        predictions.append(
            {
                "fixture_id": fixture.fixture_id,
                "prediction_date": datetime.now(UTC).date().isoformat(),
                "home_team_id": int(fixture.home_team_id),
                "away_team_id": int(fixture.away_team_id),
                "league_average_points": league_average_points,
                "home_scoring_factor": home_scoring_factor,
                "away_scoring_factor": away_scoring_factor,
                "home_attack_multiplier": home_attack_multiplier,
                "home_defence_multiplier": home_defence_multiplier,
                "away_attack_multiplier": away_attack_multiplier,
                "away_defence_multiplier": away_defence_multiplier,
                "expected_home_score": expected_home_score,
                "expected_away_score": expected_away_score,
            }
        )

    return pd.DataFrame(
        predictions,
        columns=PREDICTION_COLUMNS,
    )


def upsert_expected_score_predictions(
    connection: sqlite3.Connection,
    predictions: pd.DataFrame,
) -> int:
    """Insert or update expected-score predictions."""
    if predictions.empty:
        return 0

    missing_columns = set(PREDICTION_COLUMNS).difference(predictions.columns)

    if missing_columns:
        raise ValueError(
            f"Prediction data is missing columns: {sorted(missing_columns)}"
        )

    sql = """
        INSERT INTO expected_score_predictions (
            fixture_id,
            prediction_date,
            home_team_id,
            away_team_id,
            league_average_points,
            home_scoring_factor,
            away_scoring_factor,
            home_attack_multiplier,
            home_defence_multiplier,
            away_attack_multiplier,
            away_defence_multiplier,
            expected_home_score,
            expected_away_score
        )
        VALUES (
            :fixture_id,
            :prediction_date,
            :home_team_id,
            :away_team_id,
            :league_average_points,
            :home_scoring_factor,
            :away_scoring_factor,
            :home_attack_multiplier,
            :home_defence_multiplier,
            :away_attack_multiplier,
            :away_defence_multiplier,
            :expected_home_score,
            :expected_away_score
        )
        ON CONFLICT (fixture_id)
        DO UPDATE SET
            prediction_date = excluded.prediction_date,
            home_team_id = excluded.home_team_id,
            away_team_id = excluded.away_team_id,
            league_average_points =
                excluded.league_average_points,
            home_scoring_factor =
                excluded.home_scoring_factor,
            away_scoring_factor =
                excluded.away_scoring_factor,
            home_attack_multiplier =
                excluded.home_attack_multiplier,
            home_defence_multiplier =
                excluded.home_defence_multiplier,
            away_attack_multiplier =
                excluded.away_attack_multiplier,
            away_defence_multiplier =
                excluded.away_defence_multiplier,
            expected_home_score =
                excluded.expected_home_score,
            expected_away_score =
                excluded.expected_away_score,
            updated_at = CURRENT_TIMESTAMP
    """

    records = predictions[PREDICTION_COLUMNS].to_dict(orient="records")

    connection.executemany(
        sql,
        records,
    )

    return len(records)


def rebuild_expected_score_predictions(
    connection: sqlite3.Connection,
) -> int:
    """Build and persist expected scores for future fixtures."""
    predictions = build_expected_score_predictions(
        connection=connection,
    )

    return upsert_expected_score_predictions(
        connection=connection,
        predictions=predictions,
    )
