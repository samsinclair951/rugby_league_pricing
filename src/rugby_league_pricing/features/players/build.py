"""Build and rebuild base player-rating rows from Patreon player files."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from .upsert import upsert_player_ratings

PROJECT_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").exists()
)

PATREON_PLAYER_DIR = PROJECT_ROOT / "data" / "raw" / "patreon" / "players"

# Relative importance weighting per position id.
# Spine (1, 6, 7, 9) and props (8, 10) get the highest weights.
POSITION_IMPORTANCE: dict[int, float] = {
    1: 1.35,   # Fullback
    2: 1.10,   # Wing
    3: 1.05,   # Centre
    4: 1.00,   # Centre
    5: 1.00,   # Wing
    6: 1.25,   # Stand-off
    7: 1.20,   # Scrum-half
    8: 1.18,   # Prop
    9: 1.25,   # Hooker
    10: 1.18,  # Prop
    11: 1.05,  # Second-row
    12: 1.05,  # Second-row
    13: 1.05,  # Loose-forward
    14: 1.00,
    15: 1.00,
    16: 1.00,
    17: 1.00,
}

ROLE_BUCKETS: dict[str, tuple[int, ...]] = {
    "fullback": (1,),
    "halfback": (6, 7),
    "hooker": (9,),
    "prop": (8, 10),
    "middle_pack": (8, 10, 11, 12, 13),
    "back_line": (1, 2, 3, 4, 5),
    "forwards": (8, 9, 10, 11, 12, 13),
}


def load_player_data(directory: Path | None = None) -> pd.DataFrame:
    """Load and validate all Patreon player rows from CSV files."""
    player_dir = directory or PATREON_PLAYER_DIR

    if not player_dir.exists():
        raise FileNotFoundError(f"Player directory not found: {player_dir}")

    files = sorted(player_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No player CSV files found in {player_dir}")

    raw = pd.concat([pd.read_csv(path) for path in files], ignore_index=True)

    required = {
        "fixture_id",
        "player_id",
        "player_name",
        "position_id",
        "team_id",
        "opposition_id",
        "tries",
        "goals_made",
        "drop_goals",
        "tackles_made",
        "tackles_missed",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"Player data is missing expected columns: {sorted(missing)}")

    raw = raw.copy()
    raw["fixture_id"] = raw["fixture_id"].astype(str)
    raw["player_id"] = raw["player_id"].astype(str)
    raw["player_name"] = raw["player_name"].astype(str)
    raw["team_id"] = raw["team_id"].astype(str)
    raw["position_id"] = pd.to_numeric(raw["position_id"], errors="coerce")

    for col in ["tries", "goals_made", "drop_goals", "tackles_made", "tackles_missed"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce").fillna(0.0)

    return raw


def normalize_player_data(
    connection: sqlite3.Connection,
    raw: pd.DataFrame,
) -> pd.DataFrame:
    """Map Patreon fixture, team and player identifiers to canonical DB identifiers."""

    frame = raw.copy()

    # Preserve the Patreon/source identifiers.
    frame = frame.rename(
        columns={
            "fixture_id": "source_fixture_id",
            "team_id": "source_team_name",
            "player_id": "source_player_id",
        }
    )

    frame["source_fixture_id"] = frame["source_fixture_id"].astype(str)
    frame["source_team_name"] = frame["source_team_name"].astype(str)
    frame["source_player_id"] = frame["source_player_id"].astype(str)

    # ------------------------------------------------------------------
    # 1. Patreon fixture id -> canonical fixture id + season
    # ------------------------------------------------------------------
    fixture_mappings = pd.read_sql_query(
        """
        SELECT
            CAST(fsm.source_fixture_id AS TEXT) AS source_fixture_id,
            CAST(f.fixture_id AS TEXT) AS fixture_id,
            f.season
        FROM fixture_source_mappings fsm
        JOIN fixtures f
            ON f.fixture_id = fsm.fixture_id
        WHERE fsm.source_name = 'patreon'
        """,
        connection,
    )

    fixture_mappings["source_fixture_id"] = (
        fixture_mappings["source_fixture_id"].astype(str)
    )

    frame = frame.merge(
        fixture_mappings,
        on="source_fixture_id",
        how="left",
        validate="many_to_one",
    )

    missing_fixture = frame["fixture_id"].isna()
    if missing_fixture.any():
        examples = (
            frame.loc[missing_fixture, "source_fixture_id"]
            .drop_duplicates()
            .head(10)
            .tolist()
        )
        raise ValueError(
            f"{missing_fixture.sum()} player rows could not be mapped to canonical "
            f"fixtures. Example Patreon fixture ids: {examples}"
        )

    # ------------------------------------------------------------------
    # 2. Patreon team name -> canonical team id
    # ------------------------------------------------------------------
    team_mappings = pd.read_sql_query(
        """
        SELECT
            team_id,
            source_team_name,
            valid_from_season,
            valid_to_season
        FROM team_source_mappings
        WHERE source_name = 'patreon'
        """,
        connection,
    )

    team_mappings["source_team_name"] = (
        team_mappings["source_team_name"].astype(str)
    )

    frame = frame.merge(
        team_mappings,
        on="source_team_name",
        how="left",
    )

    valid_team_mapping = (
        (
            frame["valid_from_season"].isna()
            | (frame["season"] >= frame["valid_from_season"])
        )
        &
        (
            frame["valid_to_season"].isna()
            | (frame["season"] <= frame["valid_to_season"])
        )
    )

    frame = frame.loc[valid_team_mapping].copy()

    missing_team = frame["team_id"].isna()
    if missing_team.any():
        examples = (
            frame.loc[missing_team, ["source_team_name", "season"]]
            .drop_duplicates()
            .head(10)
            .to_dict("records")
        )
        raise ValueError(
            f"{missing_team.sum()} player rows could not be mapped to canonical "
            f"teams. Examples: {examples}"
        )

    frame["team_id"] = frame["team_id"].astype(int)

    # ------------------------------------------------------------------
    # 3. Patreon player id -> canonical player id
    #
    # This relies on players.source_name/source_player_id containing
    # the Patreon player mapping.
    # ------------------------------------------------------------------
    player_mappings = pd.read_sql_query(
        """
        SELECT
            player_id AS canonical_player_id,
            source_player_id,
            season,
            team_id
        FROM player_source_mappings
        WHERE source_name = 'patreon'
        """,
        connection,
    )

    if player_mappings.empty:
        raise ValueError(
            "No Patreon player mappings exist in players. "
            "Cannot map Patreon player_id values to canonical player_id values."
        )

    player_mappings["source_player_id"] = (
        player_mappings["source_player_id"].astype(str)
    )

    frame = frame.merge(
        player_mappings,
        on=["source_player_id", "season", "team_id"],
        how="left",
        validate="many_to_one",
    )

    missing_player = frame["canonical_player_id"].isna()

    if missing_player.any():
        print(
            f"Skipping {missing_player.sum()} player rows with no canonical "
            f"player mapping."
        )

        frame = frame.loc[~missing_player].copy()

    frame["player_id"] = frame["canonical_player_id"].astype(str)

    # No longer need mapping-only columns.
    frame = frame.drop(
        columns=[
            "canonical_player_id",
            "valid_from_season",
            "valid_to_season",
        ],
        errors="ignore",
    )

    return frame


def _compute_ratings(players: pd.DataFrame) -> pd.DataFrame:
    """Compute attack, defence, and overall ratings per fixture/player row."""
    players = players.copy()

    # Deduplicate so one player has one row per fixture/team.
    id_cols = [
        "fixture_id",
        "player_id",
        "player_name",
        "position_id",
        "team_id",
        "season",
    ]
    numeric_cols = (
        players.select_dtypes(include=np.number)
        .columns.difference(id_cols)
        .tolist()
    )
    players = players.groupby(["fixture_id", "player_id"], as_index=False).agg(
        {
            "player_name": "first",
            "position_id": "first",
            "team_id": "first",
            "season": "first",
            **{c: "sum" for c in numeric_cols},
        }
    )

    players["player_points"] = (
        4 * players["tries"]
        + 2 * players["goals_made"]
        + players["drop_goals"]
    )
    players["player_value"] = (
        players["player_points"]
        + 0.5 * players["tries"]
        + 0.25 * players["goals_made"]
        + 0.15 * players["tackles_made"]
        - 0.25 * players["tackles_missed"]
    )

    team_totals = (
        players.groupby(["fixture_id", "team_id"], as_index=False)["player_points"]
        .sum()
        .rename(columns={"player_points": "team_points"})
    )
    players = players.merge(team_totals, on=["fixture_id", "team_id"], how="left")

    players["team_share"] = np.where(
        players["team_points"].replace(0, np.nan).notna(),
        players["player_value"] / players["team_points"],
        0.0,
    )
    players["position_factor"] = (
        players["position_id"].map(POSITION_IMPORTANCE).fillna(1.0)
    )

    players["attack_rating"] = 10.0 * players["team_share"] * players["position_factor"]
    players["defence_rating"] = (
        (players["tackles_made"] - 0.5 * players["tackles_missed"])
        * 0.12
        * players["position_factor"]
    )
    players["overall_rating"] = players["attack_rating"] + players["defence_rating"]

    appearance_counts = (
        players.groupby("player_id")["fixture_id"].transform("count")
    )
    players["reliability"] = np.clip(np.sqrt(appearance_counts / 20.0), 0.0, 1.0)

    return players


def build_player_ratings(
    connection: sqlite3.Connection,
    directory: Path | None = None,
) -> pd.DataFrame:
    """Build a database-ready player-ratings frame.

    Loads Patreon player files, computes per-fixture ratings, and joins
    to the fixtures table for the season field.
    """
    raw = load_player_data(directory=directory)
    raw = normalize_player_data(
        connection=connection,
        raw=raw,
    )
    players = _compute_ratings(raw)

    if players["season"].isna().any():
        fallback = pd.to_numeric(
            players["fixture_id"].str[:4],
            errors="coerce",
        ).fillna(0)
        players["season"] = players["season"].fillna(fallback)

    players["season"] = pd.to_numeric(players["season"], errors="coerce").fillna(0).astype(int)
    players["position_id"] = pd.to_numeric(players["position_id"], errors="coerce")

    return players[
        [
            "fixture_id",
            "team_id",
            "player_id",
            "player_name",
            "position_id",
            "season",
            "attack_rating",
            "defence_rating",
            "overall_rating",
            "reliability",
        ]
    ].copy()


def _team_selection_value(
    team_ratings: pd.DataFrame,
    *,
    rating_column: str,
) -> float:
    """Summarise the actual team selection for the current fixture."""
    return float(team_ratings[rating_column].sum())


def _best_role_value(
    recent_ratings: pd.DataFrame,
    team_id: str,
    positions: tuple[int, ...],
) -> tuple[float, float, float]:
    """Return the strongest recent value for a role bucket."""
    subset = recent_ratings[
        (recent_ratings["team_id"] == str(team_id))
        & (recent_ratings["position_id"].isin(positions))
    ].copy()

    if subset.empty:
        return 0.0, 0.0, 0.0

    best_row = subset.sort_values(
        ["overall_rating", "reliability"],
        ascending=False,
    ).iloc[0]

    return (
        float(best_row["overall_rating"]),
        float(best_row["attack_rating"]),
        float(best_row["defence_rating"]),
    )


def build_full_strength_reference(
    connection: sqlite3.Connection,
    fixture_ids: list[str] | None = None,
    window: int = 8,
) -> pd.DataFrame:
    """Construct a rolling full-strength team reference from recent player ratings.

    The reference is built from the strongest recent player in each key role bucket,
    then compared to the actual team selection for the fixture. The resulting
    selection gap is a useful input for a baseline team-strength adjustment before
    lineup-specific team-news overrides are applied.
    """
    if window <= 0:
        raise ValueError("window must be positive.")

    if fixture_ids is None:
        fixtures = pd.read_sql_query(
            """
            SELECT fixture_id, match_date, season, home_team_id, away_team_id
            FROM fixtures
            ORDER BY match_date, fixture_id
            """,
            connection,
            parse_dates=["match_date"],
        )
        fixture_ids = fixtures["fixture_id"].astype(str).tolist()

    fixture_ids = [str(fixture_id) for fixture_id in fixture_ids]
    if not fixture_ids:
        return pd.DataFrame(
            columns=[
                "fixture_id",
                "team_id",
                "match_date",
                "season",
                "actual_team_value",
                "full_strength_value",
                "full_strength_attack_value",
                "full_strength_defence_value",
                "selection_gap",
                "selection_gap_ratio",
            ]
        )

    fixtures = pd.read_sql_query(
        """
        SELECT fixture_id, match_date, season, home_team_id, away_team_id
        FROM fixtures
        WHERE fixture_id IN ({})
        ORDER BY match_date, fixture_id
        """.format(", ".join("?" for _ in fixture_ids)),
        connection,
        params=fixture_ids,
        parse_dates=["match_date"],
    )

    if fixtures.empty:
        return pd.DataFrame(
            columns=[
                "fixture_id",
                "team_id",
                "match_date",
                "season",
                "actual_team_value",
                "full_strength_value",
                "full_strength_attack_value",
                "full_strength_defence_value",
                "selection_gap",
                "selection_gap_ratio",
            ]
        )

    ratings = pd.read_sql_query(
        """
        SELECT
            fixture_id,
            team_id,
            player_id,
            player_name,
            position_id,
            season,
            attack_rating,
            defence_rating,
            overall_rating,
            reliability
        FROM player_ratings
        WHERE fixture_id IN ({})
        ORDER BY fixture_id, team_id, player_id
        """.format(", ".join("?" for _ in fixture_ids)),
        connection,
        params=fixture_ids,
    )

    if ratings.empty:
        return pd.DataFrame(
            columns=[
                "fixture_id",
                "team_id",
                "match_date",
                "season",
                "actual_team_value",
                "full_strength_value",
                "full_strength_attack_value",
                "full_strength_defence_value",
                "selection_gap",
                "selection_gap_ratio",
            ]
        )

    ratings["fixture_id"] = ratings["fixture_id"].astype(str)
    ratings["team_id"] = ratings["team_id"].astype(str)
    ratings["position_id"] = pd.to_numeric(ratings["position_id"], errors="coerce")

    fixture_lookup = fixtures.set_index("fixture_id")
    rows = []

    for fixture_id, fixture_row in fixture_lookup.iterrows():
        match_date = pd.Timestamp(fixture_row["match_date"])
        season = int(fixture_row["season"])

        fixture_ratings = ratings[ratings["fixture_id"] == str(fixture_id)].copy()
        team_ids = sorted(set(fixture_ratings["team_id"].tolist()))

        for team_id in team_ids:
            actual_team = fixture_ratings[fixture_ratings["team_id"] == str(team_id)].copy()
            actual_team_value = _team_selection_value(
                actual_team,
                rating_column="overall_rating",
            )
            actual_attack_value = _team_selection_value(
                actual_team,
                rating_column="attack_rating",
            )
            actual_defence_value = _team_selection_value(
                actual_team,
                rating_column="defence_rating",
            )

            recent_fixtures = pd.read_sql_query(
                """
                SELECT pr.fixture_id, pr.team_id, pr.player_id, pr.player_name,
                       pr.position_id, pr.attack_rating, pr.defence_rating,
                       pr.overall_rating, pr.reliability, f.match_date
                FROM player_ratings pr
                JOIN fixtures f ON f.fixture_id = pr.fixture_id
                WHERE pr.team_id = ?
                  AND f.match_date < ?
                ORDER BY f.match_date DESC, pr.fixture_id DESC
                LIMIT ?
                """,
                connection,
                params=(team_id, match_date.strftime("%Y-%m-%d"), window),
            )

            recent_fixtures["team_id"] = recent_fixtures["team_id"].astype(str)
            recent_fixtures["position_id"] = pd.to_numeric(
                recent_fixtures["position_id"],
                errors="coerce",
            )

            if recent_fixtures.empty:
                full_strength_value = actual_team_value
                full_strength_attack_value = actual_attack_value
                full_strength_defence_value = actual_defence_value
            else:
                role_values = []
                role_attack = []
                role_defence = []
                for positions in ROLE_BUCKETS.values():
                    value, attack_value, defence_value = _best_role_value(
                        recent_ratings=recent_fixtures,
                        team_id=str(team_id),
                        positions=tuple(sorted(set(positions))),
                    )
                    role_values.append(value)
                    role_attack.append(attack_value)
                    role_defence.append(defence_value)

                full_strength_value = float(sum(role_values))
                full_strength_attack_value = float(sum(role_attack))
                full_strength_defence_value = float(sum(role_defence))

            selection_gap = max(0.0, full_strength_value - actual_team_value)
            selection_gap_ratio = (
                selection_gap / full_strength_value if full_strength_value > 0 else 0.0
            )

            rows.append(
                {
                    "fixture_id": str(fixture_id),
                    "team_id": int(team_id),
                    "match_date": match_date,
                    "season": season,
                    "actual_team_value": actual_team_value,
                    "full_strength_value": full_strength_value,
                    "full_strength_attack_value": full_strength_attack_value,
                    "full_strength_defence_value": full_strength_defence_value,
                    "selection_gap": selection_gap,
                    "selection_gap_ratio": selection_gap_ratio,
                }
            )

    return pd.DataFrame(rows).sort_values(
        ["match_date", "fixture_id", "team_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def rebuild_player_ratings(connection: sqlite3.Connection) -> int:
    """Build and persist player ratings to the database."""
    ratings = build_player_ratings(connection=connection)

    return upsert_player_ratings(
        connection=connection,
        player_ratings=ratings,
    )
