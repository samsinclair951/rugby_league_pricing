from __future__ import annotations

import io
import sqlite3
from datetime import date, timedelta

import numpy as np
import pandas as pd

from rugby_league_pricing.database.connection import get_connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _expected_scores_source(connection: sqlite3.Connection) -> tuple[str, str, str]:
    """Return table and expected-score column names.

    Supports the current project naming plus the earlier expected_scores table.
    """
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    candidates = ["expected_score_predictions", "expected_scores"]

    for table in candidates:
        if table not in tables:
            continue

        columns = _table_columns(connection, table)

        home_candidates = ["expected_home_score", "predicted_home_score"]
        away_candidates = ["expected_away_score", "predicted_away_score"]

        home_column = next(
            (column for column in home_candidates if column in columns),
            None,
        )
        away_column = next(
            (column for column in away_candidates if column in columns),
            None,
        )

        if home_column and away_column and "fixture_id" in columns:
            return table, home_column, away_column

    raise RuntimeError(
        "Could not find expected scores. Expected either "
        "expected_score_predictions or expected_scores with fixture_id and "
        "expected_home_score/expected_away_score columns."
    )


def load_upcoming_fixtures(*, days: int = 7) -> pd.DataFrame:
    """Load fixtures in the next seven days that have expected scores."""
    start_date = date.today()
    end_date = start_date + timedelta(days=days)

    with get_connection() as connection:
        table, home_column, away_column = _expected_scores_source(connection)

        query = f"""
            SELECT
                f.fixture_id,
                f.match_date,
                f.kick_off,
                f.home_team_id,
                ht.canonical_name AS home_team,
                f.away_team_id,
                at.canonical_name AS away_team,
                es.{home_column} AS expected_home_score,
                es.{away_column} AS expected_away_score
            FROM fixtures AS f
            JOIN teams AS ht
                ON ht.team_id = f.home_team_id
            JOIN teams AS at
                ON at.team_id = f.away_team_id
            JOIN {table} AS es
                ON es.fixture_id = f.fixture_id
                AND es.version_type = 'baseline'
            WHERE DATE(f.match_date) BETWEEN DATE(?) AND DATE(?)
            ORDER BY
                DATE(f.match_date),
                f.kick_off,
                f.fixture_id
        """

        fixtures = pd.read_sql_query(
            query,
            connection,
            params=(start_date.isoformat(), end_date.isoformat()),
        )

    if not fixtures.empty:
        fixtures["match_date"] = pd.to_datetime(fixtures["match_date"])

    return fixtures


def load_fixture(fixture_id: str) -> pd.Series:
    """Load one fixture and its expected scores."""
    with get_connection() as connection:
        table, home_column, away_column = _expected_scores_source(connection)

        query = f"""
            SELECT
                f.fixture_id,
                f.match_date,
                f.kick_off,
                f.home_team_id,
                ht.canonical_name AS home_team,
                f.away_team_id,
                at.canonical_name AS away_team,
                es.{home_column} AS expected_home_score,
                es.{away_column} AS expected_away_score
            FROM fixtures AS f
            JOIN teams AS ht
                ON ht.team_id = f.home_team_id
            JOIN teams AS at
                ON at.team_id = f.away_team_id
            JOIN {table} AS es
                ON es.fixture_id = f.fixture_id
                AND es.version_type = 'baseline'
            WHERE f.fixture_id = ?
        """

        fixture = pd.read_sql_query(query, connection, params=(fixture_id,))

    if fixture.empty:
        raise ValueError(f"Fixture {fixture_id!r} was not found.")

    fixture["match_date"] = pd.to_datetime(fixture["match_date"])
    return fixture.iloc[0]


def load_last_results(team_id: int, *, before_date: date, limit: int = 3) -> pd.DataFrame:
    """Load a team's latest completed fixtures before the selected fixture."""
    query = """
        SELECT
            r.match_date,
            r.home_team_id,
            ht.canonical_name AS home_team,
            r.home_score,
            r.away_team_id,
            at.canonical_name AS away_team,
            r.away_score
        FROM results AS r
        JOIN teams AS ht
            ON ht.team_id = r.home_team_id
        JOIN teams AS at
            ON at.team_id = r.away_team_id
        WHERE
            (r.home_team_id = ? OR r.away_team_id = ?)
            AND DATE(r.match_date) < DATE(?)
        ORDER BY DATE(r.match_date) DESC, r.fixture_id DESC
        LIMIT ?
    """

    with get_connection() as connection:
        results = pd.read_sql_query(
            query,
            connection,
            params=(team_id, team_id, before_date.isoformat(), limit),
        )

    if results.empty:
        return results

    results["match_date"] = pd.to_datetime(results["match_date"])
    results["opponent"] = np.where(
        results["home_team_id"] == team_id,
        results["away_team"],
        results["home_team"],
    )
    results["points_for"] = np.where(
        results["home_team_id"] == team_id,
        results["home_score"],
        results["away_score"],
    )
    results["points_against"] = np.where(
        results["home_team_id"] == team_id,
        results["away_score"],
        results["home_score"],
    )
    results["venue_side"] = np.where(
        results["home_team_id"] == team_id,
        "H",
        "A",
    )

    return results[
        ["match_date", "venue_side", "opponent", "points_for", "points_against"]
    ]


def load_latest_historical_matrix(*, matrix_version: str = "historical-v1") -> np.ndarray:
    """Load the latest stored historical score probability matrix."""
    query = """
        SELECT probability_matrix
        FROM historical_score_matrices
        WHERE matrix_version = ?
        ORDER BY DATE(as_of_date) DESC
        LIMIT 1
    """

    with get_connection() as connection:
        row = connection.execute(query, (matrix_version,)).fetchone()

    if row is None:
        raise ValueError(
            f"No historical matrix found for matrix_version={matrix_version!r}."
        )

    buffer = io.BytesIO(row[0])
    return np.load(buffer, allow_pickle=False)

def load_true_prices(
    fixture_id: str,
    version_type: str = "baseline",
) -> pd.DataFrame:
    """Load stored true prices for one fixture/version."""
    query = """
        SELECT
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
        FROM true_prices
        WHERE fixture_id = ?
          AND version_type = ?
        ORDER BY market, line, selection
    """

    with get_connection() as connection:
        prices = pd.read_sql_query(
            query,
            connection,
            params=(fixture_id, version_type),
        )

    return prices


def load_true_price_bundle(
    fixture_id: str,
    version_type: str = "baseline",
) -> dict[str, pd.DataFrame | float]:
    """Load stored true prices and reshape them for the dashboard."""
    prices = load_true_prices(
        fixture_id=fixture_id,
        version_type=version_type,
    )

    if prices.empty:
        raise ValueError(
            f"No true prices found for fixture_id={fixture_id!r}, "
            f"version_type={version_type!r}."
        )

    match_odds = prices.loc[
        prices["market"].eq("match_odds")
    ].copy()

    handicap_rows = prices.loc[
        prices["market"].eq("handicap")
    ].copy()

    total_rows = prices.loc[
        prices["market"].eq("total")
    ].copy()

    if handicap_rows.empty:
        raise ValueError("No handicap prices found.")

    if total_rows.empty:
        raise ValueError("No total prices found.")

    main_handicap = float(
        handicap_rows["line"].iloc[0]
    )

    main_total = float(
        total_rows["line"].iloc[0]
    )

    handicaps = (
        handicap_rows
        .pivot(
            index="line",
            columns="selection",
            values="decimal_price",
        )
        .reset_index()
        .rename(
            columns={
                "home": "home_price",
                "away": "away_price",
            }
        )
    )

    totals = (
        total_rows
        .pivot(
            index="line",
            columns="selection",
            values="decimal_price",
        )
        .reset_index()
        .rename(
            columns={
                "over": "over_price",
                "under": "under_price",
            }
        )
    )

    return {
        "match_odds": match_odds,
        "handicaps": handicaps,
        "totals": totals,
        "main_handicap": main_handicap,
        "main_total": main_total,
        "expected_home_score": float(
            prices["expected_home_score"].iloc[0]
        ),
        "expected_away_score": float(
            prices["expected_away_score"].iloc[0]
        ),
    }


def load_true_price_versions(
    fixture_id: str,
) -> list[str]:
    """Return stored pricing versions for a fixture."""
    query = """
        SELECT DISTINCT version_type
        FROM true_prices
        WHERE fixture_id = ?
        ORDER BY version_type
    """

    with get_connection() as connection:
        rows = connection.execute(
            query,
            (fixture_id,),
        ).fetchall()

    return [str(row[0]) for row in rows]