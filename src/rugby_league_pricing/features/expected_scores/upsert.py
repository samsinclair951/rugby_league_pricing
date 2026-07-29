"""Upsert helpers for expected-score rows."""

from __future__ import annotations

import sqlite3

import pandas as pd

from rugby_league_pricing.utils.sql import upsert_dataframe

from .constants import EXPECTED_SCORES_UPSERT_COLUMNS


def upsert_expected_scores(
    connection: sqlite3.Connection,
    expected_scores: pd.DataFrame,
) -> int:
    """Insert or update expected scores."""
    if expected_scores.empty:
        return 0

    missing_columns = set(EXPECTED_SCORES_UPSERT_COLUMNS).difference(
        expected_scores.columns
    )

    if missing_columns:
        raise ValueError(
            f"Expected scores missing required columns: {sorted(missing_columns)}"
        )

    return upsert_dataframe(
        connection=connection,
        dataframe=expected_scores,
        table_name="expected_scores",
        columns=EXPECTED_SCORES_UPSERT_COLUMNS,
        conflict_columns=["fixture_id"],
        update_timestamp=True,
    )
