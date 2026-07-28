from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd


def prepare_database_rows(
    dataframe: pd.DataFrame,
    columns: list[str],
) -> list[tuple]:
    """Convert a DataFrame into SQLite-compatible rows."""
    rows = []

    for row in dataframe[columns].itertuples(index=False, name=None):
        converted = []

        for value in row:
            if pd.isna(value):
                converted.append(None)
            elif isinstance(value, pd.Timestamp):
                converted.append(value.date().isoformat())
            elif isinstance(value, np.generic):
                converted.append(value.item())
            else:
                converted.append(value)

        rows.append(tuple(converted))

    return rows


def upsert_dataframe(
    connection: sqlite3.Connection,
    dataframe: pd.DataFrame,
    table_name: str,
    columns: list[str],
    conflict_columns: list[str],
    update_columns: list[str] | None = None,
    update_timestamp: bool = False,
) -> int:
    """Insert or update a DataFrame in a SQLite table."""
    if dataframe.empty:
        return 0

    missing_columns = [column for column in columns if column not in dataframe.columns]

    if missing_columns:
        raise ValueError(f"DataFrame is missing required columns: {missing_columns}")

    rows = prepare_database_rows(
        dataframe=dataframe,
        columns=columns,
    )

    insert_columns = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    conflict_clause = ", ".join(conflict_columns)

    if update_columns is None:
        update_columns = [
            column for column in columns if column not in conflict_columns
        ]

    invalid_update_columns = [
        column for column in update_columns if column not in columns
    ]

    if invalid_update_columns:
        raise ValueError(
            f"Update columns are not present in insert columns: "
            f"{invalid_update_columns}"
        )

    update_assignments = [f"{column} = excluded.{column}" for column in update_columns]

    if update_timestamp:
        update_assignments.append("updated_at = CURRENT_TIMESTAMP")

    update_clause = ", ".join(update_assignments)

    query = f"""
        INSERT INTO {table_name} ({insert_columns})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_clause})
        DO UPDATE SET
            {update_clause}
    """

    connection.executemany(query, rows)

    return len(rows)
