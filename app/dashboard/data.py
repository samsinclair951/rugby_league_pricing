from __future__ import annotations

import io
import logging
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from rugby_league_pricing.database.connection import get_connection
from rugby_league_pricing.features.expected_scores.predict import (
    PREDICTION_COLUMNS,
    calculate_scoring_factors,
    fixture_team_strength,
    load_completed_results,
    load_strength_multipliers,
    upsert_expected_score_predictions,
)
from rugby_league_pricing.features.strength_multipliers import (
    rebuild_strength_multipliers,
)
from rugby_league_pricing.features.strength_multipliers.blended_final import (
    build_final_strength_multipliers,
    predict_from_stored_model,
)
from rugby_league_pricing.features.strength_multipliers.model_store import (
    load_latest_player_blend_model,
)
from rugby_league_pricing.features.strength_multipliers.upsert import (
    upsert_strength_multipliers,
)
from rugby_league_pricing.features.team_lineups.adjustment_upsert import (
    upsert_team_selection_adjustments,
)
from rugby_league_pricing.features.team_lineups.strength import (
    build_team_lineup_strength,
)
from rugby_league_pricing.features.team_lineups.upsert import (
    upsert_expected_team_lineups,
)
from rugby_league_pricing.pricing.score_matrices.blend import (
    build_blended_score_matrix,
)
from rugby_league_pricing.pricing.true_prices.mainline_handicap import (
    MainlineHandicapPricer,
)
from rugby_league_pricing.pricing.true_prices.mainline_totals import (
    MainlineTotalsPricer,
)
from rugby_league_pricing.pricing.true_prices.match_odds import (
    MatchOddsPricer,
)


LOGGER = logging.getLogger(__name__)


def _lineup_log(message: str) -> None:
    LOGGER.info(message)
    print(message)


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
    start_date = datetime.now(UTC).date()
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

    handicap_main = handicap_rows.loc[
        handicap_rows["selection"].eq("home")
    ].copy()
    if handicap_main.empty:
        raise ValueError("No home handicap prices found.")
    handicap_main["distance_to_even"] = (
        handicap_main["probability"] - 0.5
    ).abs()

    main_handicap = float(
        handicap_main.sort_values(
            ["distance_to_even", "line"]
        ).iloc[0]["line"]
    )

    total_main = total_rows.loc[
        total_rows["selection"].eq("over")
    ].copy()
    if total_main.empty:
        raise ValueError("No over total prices found.")
    total_main["distance_to_even"] = (
        total_main["probability"] - 0.5
    ).abs()

    main_total = float(
        total_main.sort_values(
            ["distance_to_even", "line"]
        ).iloc[0]["line"]
    )

    handicaps = (
        handicap_rows
        .pivot(
            index="line",
            columns="selection",
            values="decimal_price",
        )
        .sort_index()
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
        .sort_index()
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


EDITABLE_VERSION_TYPES = [
    "pre_preview_expected_line_up",
    "preview_expected_line_up",
    "confirmed_line_up",
]

TRUE_PRICE_MODEL_VERSION = "negative-binomial-historical-v1"
CORE_STARTER_POSITIONS = tuple(range(1, 14))


def _fixture_meta(
    connection: sqlite3.Connection,
    fixture_id: str,
) -> pd.Series:
    meta = pd.read_sql_query(
        """
        SELECT
            fixture_id,
            season,
            match_date,
            home_team_id,
            away_team_id
        FROM fixtures
        WHERE fixture_id = ?
        """,
        connection,
        params=(fixture_id,),
        parse_dates=["match_date"],
    )

    if meta.empty:
        raise ValueError(f"Unknown fixture_id: {fixture_id}")

    return meta.iloc[0]


def _load_expected_lineup(
    connection: sqlite3.Connection,
    fixture_id: str,
    version_type: str,
) -> pd.DataFrame:
    lineup = pd.read_sql_query(
        """
        SELECT
            fixture_id,
            team_id,
            player_id,
            player_name,
            position_id,
            version_type,
            notes
        FROM expected_team_lineups
        WHERE fixture_id = ?
          AND version_type = ?
        ORDER BY team_id, position_id, player_name
        """,
        connection,
        params=(fixture_id, version_type),
    )

    if not lineup.empty:
        return lineup

    # For preview editing, default to pre-preview if preview has not been
    # authored yet.
    if version_type == "preview_expected_line_up":
        lineup = pd.read_sql_query(
            """
            SELECT
                fixture_id,
                team_id,
                player_id,
                player_name,
                position_id,
                ? AS version_type,
                notes
            FROM expected_team_lineups
            WHERE fixture_id = ?
              AND version_type = 'pre_preview_expected_line_up'
            ORDER BY team_id, position_id, player_name
            """,
            connection,
            params=(version_type, fixture_id),
        )

    if lineup.empty and version_type == "confirmed_line_up":
        lineup = pd.read_sql_query(
            """
            SELECT
                ts.fixture_id,
                ts.team_id,
                CAST(ts.player_id AS TEXT) AS player_id,
                COALESCE(
                    NULLIF(p.player_name, ''),
                    CAST(ts.player_id AS TEXT)
                ) AS player_name,
                CASE
                    WHEN NULLIF(TRIM(ts.position), '') IS NOT NULL
                     AND TRIM(ts.position) NOT GLOB '*[^0-9]*'
                     AND CAST(ts.position AS INTEGER) BETWEEN 1 AND 18
                        THEN CAST(ts.position AS INTEGER)
                    ELSE ts.lineup_order
                END AS position_id,
                'confirmed_line_up' AS version_type,
                'Loaded from teamsheets for dashboard editing' AS notes
            FROM teamsheets ts
            JOIN fixtures f
                ON f.fixture_id = ts.fixture_id
            LEFT JOIN players p
                ON p.player_id = ts.player_id
               AND p.team_id = ts.team_id
               AND p.season = f.season
            WHERE ts.fixture_id = ?
            ORDER BY ts.team_id, ts.lineup_order
            """,
            connection,
            params=(fixture_id,),
        )

    return lineup


def _normalize_team_positions(
    lineup_rows: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Repair missing starter slots (1-13) using duplicate/bench positions."""
    if lineup_rows.empty:
        return lineup_rows, {
            "missing_before": [],
            "missing_after": [],
            "reassigned": 0,
        }

    frame = lineup_rows.copy()
    frame["position_id"] = pd.to_numeric(
        frame["position_id"],
        errors="coerce",
    )
    frame = frame.reset_index(drop=True)

    before_positions = [
        int(value)
        for value in frame["position_id"].dropna().tolist()
        if 1 <= int(value) <= 18
    ]
    missing_before = [
        position
        for position in CORE_STARTER_POSITIONS
        if position not in before_positions
    ]

    seen: set[int] = set()
    invalid_or_duplicate_idx: list[int] = []
    bench_idx: list[int] = []

    for idx, raw_position in frame["position_id"].items():
        if pd.isna(raw_position):
            invalid_or_duplicate_idx.append(idx)
            continue

        position = int(raw_position)

        if position < 1 or position > 18:
            invalid_or_duplicate_idx.append(idx)
            continue

        if position in seen:
            invalid_or_duplicate_idx.append(idx)
            continue

        seen.add(position)

        if position > 13:
            bench_idx.append(idx)

    reassign_pool: list[int] = []
    for idx in invalid_or_duplicate_idx + bench_idx:
        if idx not in reassign_pool:
            reassign_pool.append(idx)

    reassigned = 0
    for position, idx in zip(missing_before, reassign_pool, strict=False):
        frame.at[idx, "position_id"] = position
        reassigned += 1

    frame["position_id"] = (
        pd.to_numeric(frame["position_id"], errors="coerce")
        .fillna(18)
        .astype(int)
    )

    after_positions = frame["position_id"].tolist()
    missing_after = [
        position
        for position in CORE_STARTER_POSITIONS
        if position not in after_positions
    ]

    return frame, {
        "missing_before": missing_before,
        "missing_after": missing_after,
        "reassigned": reassigned,
    }


def _normalize_lineup_positions(
    lineup_rows: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    normalized_groups: list[pd.DataFrame] = []
    diagnostics: list[dict[str, object]] = []

    for team_id, team_rows in lineup_rows.groupby("team_id", sort=False):
        normalized, detail = _normalize_team_positions(team_rows)
        normalized_groups.append(normalized)
        diagnostics.append(
            {
                "team_id": int(team_id),
                **detail,
            }
        )

    return pd.concat(normalized_groups, ignore_index=True), diagnostics


def load_lineup_editor_data(
    fixture_id: str,
    version_type: str,
) -> dict[str, pd.DataFrame | int | str]:
    if version_type not in EDITABLE_VERSION_TYPES:
        raise ValueError(
            f"Unsupported editable version_type: {version_type}"
        )

    with get_connection() as connection:
        fixture = _fixture_meta(
            connection=connection,
            fixture_id=fixture_id,
        )

        lineup = _load_expected_lineup(
            connection=connection,
            fixture_id=fixture_id,
            version_type=version_type,
        )

        team_ids = [
            int(fixture["home_team_id"]),
            int(fixture["away_team_id"]),
        ]

        players = pd.read_sql_query(
            """
            WITH team_players AS (
                SELECT
                    ts.team_id,
                    CAST(ts.player_id AS TEXT) AS player_id,
                    COALESCE(
                        MAX(NULLIF(p.player_name, '')),
                        CAST(ts.player_id AS TEXT)
                    ) AS player_name,
                    COUNT(*) AS appearances
                FROM teamsheets ts
                JOIN fixtures f
                    ON f.fixture_id = ts.fixture_id
                LEFT JOIN players p
                    ON p.player_id = ts.player_id
                   AND p.team_id = ts.team_id
                   AND p.season = f.season
                WHERE f.season = ?
                  AND ts.team_id IN (?, ?)
                GROUP BY ts.team_id, ts.player_id
            )
            SELECT
                team_id,
                player_id,
                player_name,
                appearances
            FROM team_players
            ORDER BY team_id, appearances DESC, player_name
            """,
            connection,
            params=(
                int(fixture["season"]),
                team_ids[0],
                team_ids[1],
            ),
        )

    _lineup_log(
        "[lineup-edit] load editor data "
        f"fixture_id={fixture_id} "
        f"version_type={version_type} "
        f"lineup_rows={len(lineup)} "
        f"player_pool_rows={len(players)}"
    )

    return {
        "fixture_id": fixture_id,
        "version_type": version_type,
        "home_team_id": int(fixture["home_team_id"]),
        "away_team_id": int(fixture["away_team_id"]),
        "lineup": lineup,
        "players": players,
    }


def _build_single_prediction_row(
    connection: sqlite3.Connection,
    fixture_id: str,
    version_type: str,
) -> pd.DataFrame:
    fixture = _fixture_meta(
        connection=connection,
        fixture_id=fixture_id,
    )

    fixture_date = pd.Timestamp(
        fixture["match_date"]
    )

    strength = load_strength_multipliers(
        connection=connection,
    )

    results = load_completed_results(
        connection=connection,
    )

    (
        league_average_points,
        home_scoring_factor,
        away_scoring_factor,
    ) = calculate_scoring_factors(
        results=results,
        fixture_date=fixture_date,
    )

    home_team_id = int(fixture["home_team_id"])
    away_team_id = int(fixture["away_team_id"])

    home_strength = fixture_team_strength(
        strength=strength,
        fixture_id=fixture_id,
        team_id=home_team_id,
        version_type=version_type,
    )

    away_strength = fixture_team_strength(
        strength=strength,
        fixture_id=fixture_id,
        team_id=away_team_id,
        version_type=version_type,
    )

    expected_home_score = (
        league_average_points
        * home_scoring_factor
        * float(home_strength["scaled_attack_multiplier"])
        * float(away_strength["scaled_defence_multiplier"])
    )

    expected_away_score = (
        league_average_points
        * away_scoring_factor
        * float(away_strength["scaled_attack_multiplier"])
        * float(home_strength["scaled_defence_multiplier"])
    )

    row = {
        "fixture_id": fixture_id,
        "version_type": version_type,
        "prediction_date": datetime.now(UTC).date().isoformat(),
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "league_average_points": league_average_points,
        "home_scoring_factor": home_scoring_factor,
        "away_scoring_factor": away_scoring_factor,
        "home_attack_multiplier": float(home_strength["scaled_attack_multiplier"]),
        "home_defence_multiplier": float(home_strength["scaled_defence_multiplier"]),
        "away_attack_multiplier": float(away_strength["scaled_attack_multiplier"]),
        "away_defence_multiplier": float(away_strength["scaled_defence_multiplier"]),
        "expected_home_score": float(expected_home_score),
        "expected_away_score": float(expected_away_score),
    }

    return pd.DataFrame([row], columns=PREDICTION_COLUMNS)


def _build_fixture_adjustments(
    connection: sqlite3.Connection,
    fixture: pd.Series,
    version_type: str,
) -> pd.DataFrame:
    """Build player-selection adjustments for one fixture and version."""
    fixture_id = str(
        fixture["fixture_id"]
    )

    match_date = pd.Timestamp(
        fixture["match_date"]
    )

    home_team_id = int(
        fixture["home_team_id"]
    )

    away_team_id = int(
        fixture["away_team_id"]
    )

    team_rows = [
        {
            "team_id": home_team_id,
            "opponent_id": away_team_id,
            "is_home": 1,
        },
        {
            "team_id": away_team_id,
            "opponent_id": home_team_id,
            "is_home": 0,
        },
    ]

    rows: list[pd.DataFrame] = []

    for team in team_rows:
        strength = build_team_lineup_strength(
            connection=connection,
            fixture_id=fixture_id,
            team_id=team["team_id"],
            version_type=version_type,
        )

        strength["opponent_id"] = (
            team["opponent_id"]
        )

        strength["is_home"] = (
            team["is_home"]
        )

        rows.append(strength)

    lineup_strength = pd.concat(
        rows,
        ignore_index=True,
    )

    stored_model = load_latest_player_blend_model(
        connection=connection,
        before_date=match_date,
    )

    return predict_from_stored_model(
        lineup_strength=lineup_strength,
        stored_model=stored_model,
    )


def _load_fixture_predictions(
    connection: sqlite3.Connection,
    fixture_id: str,
    version_type: str | None = None,
) -> pd.DataFrame:
    version_clause = ""
    params: list[object] = [fixture_id]

    if version_type is not None:
        version_clause = " AND esp.version_type = ?"
        params.append(version_type)

    predictions = pd.read_sql_query(
        f"""
        SELECT
            esp.fixture_id,
            esp.version_type,
            esp.home_team_id,
            esp.away_team_id,
            esp.expected_home_score,
            esp.expected_away_score,
            f.match_date
        FROM expected_score_predictions esp
        JOIN fixtures f
            ON f.fixture_id = esp.fixture_id
        WHERE esp.fixture_id = ?
        {version_clause}
        ORDER BY esp.version_type
        """,
        connection,
        params=params,
        parse_dates=["match_date"],
    )

    if predictions.empty:
        raise ValueError(
            f"No expected-score predictions found for {fixture_id}"
        )

    return predictions


def _load_historical_results_for_pricing(
    connection: sqlite3.Connection,
    before_date: pd.Timestamp,
) -> pd.DataFrame:
    results = pd.read_sql_query(
        """
        SELECT
            r.home_score,
            r.away_score
        FROM results r
        JOIN fixtures f
            ON f.fixture_id = r.fixture_id
        WHERE f.match_date < ?
          AND r.home_score IS NOT NULL
          AND r.away_score IS NOT NULL
        ORDER BY f.match_date
        """,
        connection,
        params=(before_date.strftime("%Y-%m-%d"),),
    )

    if results.empty:
        raise ValueError(
            f"No historical results found before {before_date.date()}"
        )

    return results


def _upsert_true_prices(
    connection: sqlite3.Connection,
    records: list[dict[str, object]],
) -> None:
    if not records:
        return

    connection.executemany(
        """
        INSERT INTO true_prices (
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
        )
        VALUES (
            :fixture_id,
            :version_type,
            :market,
            :selection,
            :line,
            :probability,
            :decimal_price,
            :expected_home_score,
            :expected_away_score,
            :model_version,
            :generated_at
        )
        ON CONFLICT (
            fixture_id,
            version_type,
            market,
            selection,
            line
        )
        DO UPDATE SET
            probability = excluded.probability,
            decimal_price = excluded.decimal_price,
            expected_home_score = excluded.expected_home_score,
            expected_away_score = excluded.expected_away_score,
            model_version = excluded.model_version,
            generated_at = excluded.generated_at
        """,
        records,
    )


def _persist_true_prices_for_fixture(
    connection: sqlite3.Connection,
    fixture_id: str,
    version_type: str | None = None,
) -> None:
    predictions = _load_fixture_predictions(
        connection=connection,
        fixture_id=fixture_id,
        version_type=version_type,
    )

    fixture_date = pd.Timestamp(
        predictions.iloc[0]["match_date"]
    )

    historical_results = _load_historical_results_for_pricing(
        connection=connection,
        before_date=fixture_date,
    )

    generated_at = datetime.now(UTC).isoformat()

    for prediction in predictions.itertuples(index=False):
        expected_home_score = float(
            prediction.expected_home_score
        )
        expected_away_score = float(
            prediction.expected_away_score
        )

        score_matrix = build_blended_score_matrix(
            historical_results=historical_results,
            expected_home_score=expected_home_score,
            expected_away_score=expected_away_score,
        )

        probabilities = score_matrix.probabilities

        match_odds = MatchOddsPricer(
            probabilities
        ).price()

        handicap_pricer = MainlineHandicapPricer(
            probabilities,
            expected_home_score=expected_home_score,
            expected_away_score=expected_away_score,
        )

        totals_pricer = MainlineTotalsPricer(
            probabilities,
            expected_home_score=expected_home_score,
            expected_away_score=expected_away_score,
        )

        handicap_all = handicap_pricer.price_all()
        totals_all = totals_pricer.price_all()

        all_prices = [*match_odds]
        for line in sorted(handicap_all):
            all_prices.extend(handicap_all[line])
        for line in sorted(totals_all):
            all_prices.extend(totals_all[line])

        records: list[dict[str, object]] = []

        for price in all_prices:
            records.append(
                {
                    "fixture_id": fixture_id,
                    "version_type": str(prediction.version_type),
                    "market": str(price.market),
                    "selection": str(price.selection),
                    "line": (
                        0.0
                        if price.line is None
                        else float(price.line)
                    ),
                    "probability": float(price.probability),
                    "decimal_price": float(price.decimal_price),
                    "expected_home_score": expected_home_score,
                    "expected_away_score": expected_away_score,
                    "model_version": TRUE_PRICE_MODEL_VERSION,
                    "generated_at": generated_at,
                }
            )

        _upsert_true_prices(
            connection=connection,
            records=records,
        )


def save_lineup_and_reprice_fixture(
    fixture_id: str,
    version_type: str,
    lineup_rows: pd.DataFrame,
) -> dict[str, float | int | str]:
    if version_type not in EDITABLE_VERSION_TYPES:
        raise ValueError(
            f"Unsupported editable version_type: {version_type}"
        )

    required = {
        "team_id",
        "player_id",
        "player_name",
        "position_id",
    }
    missing = required.difference(lineup_rows.columns)
    if missing:
        raise ValueError(
            f"lineup_rows missing columns: {sorted(missing)}"
        )

    if lineup_rows.empty:
        raise ValueError("No lineup rows were provided.")

    started = time.perf_counter()
    _lineup_log(
        "[lineup-edit] start "
        f"fixture_id={fixture_id} "
        f"version_type={version_type} "
        f"rows={len(lineup_rows)}"
    )

    with get_connection() as connection:
        fixture = _fixture_meta(
            connection=connection,
            fixture_id=fixture_id,
        )

        fixture_date = pd.Timestamp(
            fixture["match_date"]
        ).normalize()

        framed = lineup_rows.copy()
        framed["fixture_id"] = fixture_id
        framed["version_type"] = version_type
        framed["notes"] = "Updated in dashboard lineup editor"
        framed = framed[
            [
                "fixture_id",
                "team_id",
                "player_id",
                "player_name",
                "position_id",
                "version_type",
                "notes",
            ]
        ]

        framed, normalization_details = _normalize_lineup_positions(framed)

        for detail in normalization_details:
            _lineup_log(
                "[lineup-edit] normalize "
                f"fixture_id={fixture_id} "
                f"team_id={detail['team_id']} "
                f"missing_before={detail['missing_before']} "
                f"missing_after={detail['missing_after']} "
                f"reassigned={detail['reassigned']}"
            )

        duplicate_rows = framed.duplicated(
            subset=["team_id", "player_id"],
        )
        if duplicate_rows.any():
            raise ValueError(
                "Lineup contains duplicate players for a team."
            )

        connection.execute(
            """
            DELETE FROM expected_team_lineups
            WHERE fixture_id = ?
              AND version_type = ?
            """,
            (fixture_id, version_type),
        )

        saved_lineup_rows = upsert_expected_team_lineups(
            connection=connection,
            lineups=framed,
        )
        _lineup_log(
            "[lineup-edit] upserted expected_lineup_rows="
            f"{saved_lineup_rows}"
        )

        fixture_for_adjustments = pd.Series(
            {
                "fixture_id": fixture_id,
                "match_date": fixture_date,
                "home_team_id": int(fixture["home_team_id"]),
                "away_team_id": int(fixture["away_team_id"]),
            }
        )

        adjustments = _build_fixture_adjustments(
            connection=connection,
            fixture=fixture_for_adjustments,
            version_type=version_type,
        )

        saved_adjustment_rows = upsert_team_selection_adjustments(
            connection=connection,
            adjustments=adjustments,
        )
        _lineup_log(
            "[lineup-edit] upserted adjustment_rows="
            f"{saved_adjustment_rows}"
        )

        baseline = pd.read_sql_query(
            """
            SELECT *
            FROM strength_multipliers
            WHERE fixture_id = ?
              AND version_type = 'baseline'
            ORDER BY team_id
            """,
            connection,
            params=(fixture_id,),
        )

        if baseline.empty:
            rebuild_strength_multipliers(
                connection=connection,
            )
            baseline = pd.read_sql_query(
                """
                SELECT *
                FROM strength_multipliers
                WHERE fixture_id = ?
                  AND version_type = 'baseline'
                ORDER BY team_id
                """,
                connection,
                params=(fixture_id,),
            )

        final_strength = build_final_strength_multipliers(
            baseline=baseline,
            adjustments=adjustments,
            version_type=version_type,
        )

        saved_strength_rows = upsert_strength_multipliers(
            connection=connection,
            strength_multipliers=final_strength,
            version_type=version_type,
        )
        _lineup_log(
            "[lineup-edit] upserted strength_rows="
            f"{saved_strength_rows}"
        )

        prediction_row = _build_single_prediction_row(
            connection=connection,
            fixture_id=fixture_id,
            version_type=version_type,
        )

        upsert_expected_score_predictions(
            connection=connection,
            predictions=prediction_row,
        )

        _persist_true_prices_for_fixture(
            connection=connection,
            fixture_id=fixture_id,
            version_type=version_type,
        )
        _lineup_log(
            "[lineup-edit] repriced fixture_id="
            f"{fixture_id}"
        )

        connection.commit()

    expected_home = float(
        prediction_row.iloc[0]["expected_home_score"]
    )
    expected_away = float(
        prediction_row.iloc[0]["expected_away_score"]
    )

    elapsed = time.perf_counter() - started
    _lineup_log(
        "[lineup-edit] complete "
        f"fixture_id={fixture_id} "
        f"version_type={version_type} "
        f"elapsed={elapsed:.3f}s "
        f"expected_home={expected_home:.3f} "
        f"expected_away={expected_away:.3f}"
    )

    return {
        "version_type": version_type,
        "lineup_rows": int(saved_lineup_rows),
        "adjustment_rows": int(saved_adjustment_rows),
        "strength_rows": int(saved_strength_rows),
        "expected_home_score": expected_home,
        "expected_away_score": expected_away,
    }