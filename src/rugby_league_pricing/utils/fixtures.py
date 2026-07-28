from __future__ import annotations


def build_fixture_id(
    match_date: str,
    home_team_id: int,
    away_team_id: int,
) -> str:
    """Build a unique identifier for a fixture."""

    return f"{match_date}_{home_team_id}_{away_team_id}"
