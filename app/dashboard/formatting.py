from __future__ import annotations

from datetime import datetime

import pandas as pd


def ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def fixture_date_heading(value: pd.Timestamp | datetime) -> str:
    timestamp = pd.Timestamp(value)
    return f"{timestamp.strftime('%A')} {ordinal(timestamp.day)} {timestamp.strftime('%B')}"


def signed_line(value: float) -> str:
    return f"{value:+.1f}"


def short_result_rows(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty:
        return results

    display = results.copy()
    display["Date"] = display["match_date"].dt.strftime("%d %b")
    display["Opponent"] = display.apply(
        lambda row: f"{row['venue_side']} vs {row['opponent']}",
        axis=1,
    )
    display["Score"] = display.apply(
        lambda row: f"{int(row['points_for'])}-{int(row['points_against'])}",
        axis=1,
    )
    return display[["Date", "Opponent", "Score"]]
