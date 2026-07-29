import io
import json
import sqlite3

from datetime import date

import numpy as np
import pandas as pd

from rugby_league_pricing.utils.sql import upsert_dataframe


HISTORICAL_WEIGHTS = [
    (2, 1.00),
    (4, 0.50),
    (6, 0.25),
    (999, 0.10),
]


def build_historical_scoring_matrix(
    results: pd.DataFrame,
    *,
    as_of_date: date,
    max_score: int = 100,
) -> np.ndarray:
    """
    Build a weighted historical scoreline probability matrix.

    Parameters
    ----------
    results
        Completed fixtures.

    as_of_date
        Date from which historical weights are calculated.

    max_score
        Maximum score represented in the matrix.

    Returns
    -------
    np.ndarray
        (max_score+1, max_score+1) probability matrix.
    """

    matrix = np.zeros(
        (max_score + 1, max_score + 1),
        dtype=np.float64,
    )

    total_weight = 0.0

    for row in results.itertuples(index=False):

        years_old = (as_of_date - row.fixture_date).days / 365.25

        weight = _historical_weight(years_old)

        home = min(int(row.home_score), max_score)
        away = min(int(row.away_score), max_score)

        matrix[home, away] += weight
        total_weight += weight

    matrix /= total_weight

    return matrix


def _historical_weight(years_old: float) -> float:
    """Return the configured weight for a historical result."""

    for max_age, weight in HISTORICAL_WEIGHTS:
        if years_old <= max_age:
            return weight

    raise RuntimeError("No historical weight configured.")

def serialise_matrix(matrix: np.ndarray) -> bytes:
    """Serialise a NumPy matrix into SQLite-compatible bytes."""
    buffer = io.BytesIO()
    np.save(buffer, matrix, allow_pickle=False)
    return buffer.getvalue()


def _normalise_results(results: pd.DataFrame) -> pd.DataFrame:
    """Normalise historical results into the columns expected by the matrix builder."""
    normalised_results = results.copy()

    if "fixture_date" not in normalised_results.columns:
        if "match_date" in normalised_results.columns:
            normalised_results = normalised_results.rename(columns={"match_date": "fixture_date"})
        else:
            raise ValueError("Historical results require a fixture_date or match_date column.")

    required_columns = {"fixture_date", "home_score", "away_score"}
    missing_columns = required_columns.difference(normalised_results.columns)

    if missing_columns:
        raise ValueError(
            "Historical results are missing required columns: "
            f"{sorted(missing_columns)}."
        )

    normalised_results["fixture_date"] = pd.to_datetime(
        normalised_results["fixture_date"]
    ).dt.date

    return normalised_results


def _load_results_from_database(connection: sqlite3.Connection) -> pd.DataFrame:
    """Load historical results from the database for matrix generation."""
    query = """
        SELECT
            match_date AS fixture_date,
            home_score,
            away_score
        FROM results
        ORDER BY match_date
    """

    results = pd.read_sql_query(query, connection)

    if results.empty:
        raise ValueError("No historical results are available in the results table.")

    return _normalise_results(results)


def upsert_matrix(
    connection: sqlite3.Connection,
    *,
    results: pd.DataFrame | None = None,
    as_of_date: date | None = None,
    matrix_version: str = "historical-v1",
    max_score: int = 100,
    weight_config: list[tuple[int, float]] | None = None,
) -> int:
    """Insert or update the historical score matrix."""
    if as_of_date is None:
        as_of_date = date.today()

    if weight_config is None:
        weight_config = HISTORICAL_WEIGHTS

    if results is None:
        results = _load_results_from_database(connection)

    matrix = build_historical_scoring_matrix(
        _normalise_results(results),
        as_of_date=as_of_date,
        max_score=max_score,
    )

    dataframe = pd.DataFrame(
        [
            {
                "matrix_version": matrix_version,
                "as_of_date": as_of_date,
                "max_score": max_score,
                "weight_config": json.dumps(weight_config),
                "probability_matrix": serialise_matrix(matrix),
            }
        ]
    )

    return upsert_dataframe(
        connection=connection,
        dataframe=dataframe,
        table_name="historical_score_matrices",
        columns=[
            "matrix_version",
            "as_of_date",
            "max_score",
            "weight_config",
            "probability_matrix",
        ],
        conflict_columns=[
            "matrix_version",
            "as_of_date",
        ],
        update_timestamp=True,
    )