"""Persistence helpers for player blend model snapshots."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from rugby_league_pricing.features.strength_multipliers.blended_final import (
    PlayerBlendModel,
)


@dataclass
class StoredPlayerBlendModel:
    model_version: str
    trained_through_date: pd.Timestamp
    ridge_alpha: float
    intercept: float
    missing_top3_threshold: float
    missing_halves_threshold: float
    coefficients: pd.Series
    feature_means: pd.Series
    feature_stds: pd.Series


def save_player_blend_model(
    connection: sqlite3.Connection,
    *,
    model_version: str,
    trained_through_date: pd.Timestamp,
    ridge_alpha: float,
    blend_model: PlayerBlendModel,
) -> None:
    """Persist a fitted blend model snapshot."""

    connection.execute(
        """
        INSERT INTO player_blend_models (
            model_version,
            trained_through_date,
            ridge_alpha,
            intercept,
            missing_top3_threshold,
            missing_halves_threshold
        )
        VALUES (?, ?, ?, ?, ?, ?)

        ON CONFLICT (model_version)
        DO UPDATE SET
            trained_through_date = excluded.trained_through_date,
            ridge_alpha = excluded.ridge_alpha,
            intercept = excluded.intercept,
            missing_top3_threshold = excluded.missing_top3_threshold,
            missing_halves_threshold = excluded.missing_halves_threshold
        """,
        (
            model_version,
            pd.Timestamp(trained_through_date).strftime("%Y-%m-%d"),
            float(ridge_alpha),
            float(blend_model.model.intercept_),
            float(blend_model.missing_top3_threshold),
            float(blend_model.missing_halves_threshold),
        ),
    )

    coefficient_rows = [
        (
            model_version,
            feature_name,
            float(coefficient),
        )
        for feature_name, coefficient in zip(
            blend_model.model.feature_names_in_,
            blend_model.model.coef_,
            strict=True,
        )
    ]

    connection.executemany(
        """
        INSERT INTO player_blend_coefficients (
            model_version,
            feature_name,
            coefficient
        )
        VALUES (?, ?, ?)

        ON CONFLICT (
            model_version,
            feature_name
        )
        DO UPDATE SET
            coefficient = excluded.coefficient
        """,
        coefficient_rows,
    )

    scaler_rows = [
        (
            model_version,
            feature_name,
            float(blend_model.feature_means[feature_name]),
            float(blend_model.feature_stds[feature_name]),
        )
        for feature_name in blend_model.feature_means.index
    ]

    connection.executemany(
        """
        INSERT INTO player_blend_scalers (
            model_version,
            feature_name,
            feature_mean,
            feature_std
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT (
            model_version,
            feature_name
        )
        DO UPDATE SET
            feature_mean = excluded.feature_mean,
            feature_std = excluded.feature_std
        """,
        scaler_rows,
    )

    connection.commit()


def load_latest_player_blend_model(
    connection: sqlite3.Connection,
    *,
    before_date: pd.Timestamp,
) -> StoredPlayerBlendModel:
    """
    Load the latest model trained strictly before the fixture date.
    """
    model = pd.read_sql_query(
        """
        SELECT
            model_version,
            trained_through_date,
            ridge_alpha,
            intercept,
            missing_top3_threshold,
            missing_halves_threshold
        FROM player_blend_models
        WHERE trained_through_date < ?
        ORDER BY trained_through_date DESC
        LIMIT 1
        """,
        connection,
        params=(
            pd.Timestamp(before_date).strftime("%Y-%m-%d"),
        ),
        parse_dates=["trained_through_date"],
    )

    if model.empty:
        raise ValueError(
            f"No player blend model available before {before_date}"
        )

    row = model.iloc[0]
    model_version = str(row["model_version"])

    coefficients = pd.read_sql_query(
        """
        SELECT
            feature_name,
            coefficient
        FROM player_blend_coefficients
        WHERE model_version = ?
        """,
        connection,
        params=(model_version,),
    ).set_index("feature_name")["coefficient"]

    scalers = pd.read_sql_query(
        """
        SELECT
            feature_name,
            feature_mean,
            feature_std
        FROM player_blend_scalers
        WHERE model_version = ?
        """,
        connection,
        params=(model_version,),
    ).set_index("feature_name")

    return StoredPlayerBlendModel(
        model_version=model_version,
        trained_through_date=pd.Timestamp(
            row["trained_through_date"]
        ),
        ridge_alpha=float(row["ridge_alpha"]),
        intercept=float(row["intercept"]),
        missing_top3_threshold=float(
            row["missing_top3_threshold"]
        ),
        missing_halves_threshold=float(
            row["missing_halves_threshold"]
        ),
        coefficients=coefficients,
        feature_means=scalers["feature_mean"],
        feature_stds=scalers["feature_std"],
    )