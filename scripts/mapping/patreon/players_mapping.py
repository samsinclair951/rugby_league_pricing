from __future__ import annotations

import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

import unicodedata

REPO_ROOT = Path(__file__).resolve().parents[3]

DATABASE_PATH = REPO_ROOT / "data" / "rugby_league_pricing.db"

PLAYER_FILES = [
    REPO_ROOT
    / "data"
    / "raw"
    / "patreon"
    / "players"
    / "sl_player_data_19_25.csv",
    REPO_ROOT
    / "data"
    / "raw"
    / "patreon"
    / "players"
    / "2026_sl_player_data.csv",
]

SOURCE_NAME = "patreon"


def normalise_name(value: str) -> str:
    value = str(value).strip().casefold()

    value = (
        value
        .replace("’", "'")
        .replace("`", "'")
        .replace("-", " ")
        .replace("'", "")
    )

    value = unicodedata.normalize(
        "NFKD",
        value,
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )

    return " ".join(value.split())


def similarity(left: str, right: str) -> float:
    """Return simple name similarity between 0 and 1."""
    return SequenceMatcher(
        None,
        normalise_name(left),
        normalise_name(right),
    ).ratio()


def load_patreon_players() -> pd.DataFrame:
    """Load unique Patreon players from the raw player files."""

    frames = []

    for path in PLAYER_FILES:
        if not path.exists():
            raise FileNotFoundError(
                f"Patreon player file not found: {path}"
            )

        frame = pd.read_csv(
            path,
            usecols=[
                "fixture_id",
                "player_id",
                "player_name",
                "team_id",
            ],
        )

        frames.append(frame)

    players = pd.concat(
        frames,
        ignore_index=True,
    )

    players["source_player_id"] = (
        players["player_id"]
        .astype(str)
        .str.strip()
    )

    players["player_name"] = (
        players["player_name"]
        .astype(str)
        .str.strip()
    )

    players["source_team_name"] = (
        players["team_id"]
        .astype(str)
        .str.strip()
    )

    players["source_fixture_id"] = (
        players["fixture_id"]
        .astype(str)
        .str.strip()
    )

    return players[
        [
            "source_fixture_id",
            "source_player_id",
            "player_name",
            "source_team_name",
        ]
    ].drop_duplicates()


def attach_fixture_metadata(
    players: pd.DataFrame,
) -> pd.DataFrame:
    """Attach season using raw Patreon fixture/result files."""

    fixture_files = [
        REPO_ROOT
        / "data"
        / "raw"
        / "patreon"
        / "results"
        / "sl_results_data_19_25.csv",

        REPO_ROOT
        / "data"
        / "raw"
        / "patreon"
        / "results"
        / "2026_sl_fixture_data.csv",
    ]

    frames = []

    for path in fixture_files:
        if not path.exists():
            raise FileNotFoundError(
                f"Patreon results file not found: {path}"
            )

        frame = pd.read_csv(
            path,
            usecols=[
                "fixture_id",
                "fixture_date",
            ],
        )

        frames.append(frame)

    fixtures = pd.concat(
        frames,
        ignore_index=True,
    )

    fixtures["source_fixture_id"] = (
        fixtures["fixture_id"]
        .astype(str)
        .str.strip()
    )

    fixtures["fixture_date"] = pd.to_datetime(
        fixtures["fixture_date"],
        errors="coerce",
    )

    fixtures["season"] = (
        fixtures["fixture_date"].dt.year
    )

    fixtures = (
        fixtures[
            [
                "source_fixture_id",
                "season",
            ]
        ]
        .dropna(subset=["season"])
        .drop_duplicates()
    )

    frame = players.merge(
        fixtures,
        on="source_fixture_id",
        how="left",
        validate="many_to_one",
    )

    missing = frame["season"].isna()

    if missing.any():
        examples = (
            frame.loc[
                missing,
                "source_fixture_id",
            ]
            .drop_duplicates()
            .head(10)
            .tolist()
        )

        raise ValueError(
            f"{missing.sum()} player rows "
            "could not be assigned a season. "
            f"Examples: {examples}"
        )

    frame["season"] = frame["season"].astype(int)

    return frame


def attach_team_ids(
    connection: sqlite3.Connection,
    players: pd.DataFrame,
) -> pd.DataFrame:
    """Resolve Patreon team names to canonical team IDs."""

    mappings = pd.read_sql_query(
        """
        SELECT
            team_id,
            source_team_name,
            valid_from_season,
            valid_to_season
        FROM team_source_mappings
        WHERE source_name = ?
        """,
        connection,
        params=(SOURCE_NAME,),
    )

    frame = players.merge(
        mappings,
        on="source_team_name",
        how="left",
    )

    valid = (
        (
            frame["valid_from_season"].isna()
            | (
                frame["season"]
                >= frame["valid_from_season"]
            )
        )
        &
        (
            frame["valid_to_season"].isna()
            | (
                frame["season"]
                <= frame["valid_to_season"]
            )
        )
    )

    frame = frame.loc[valid].copy()

    if frame["team_id"].isna().any():
        missing = (
            frame.loc[
                frame["team_id"].isna(),
                ["source_team_name", "season"],
            ]
            .drop_duplicates()
            .to_dict("records")
        )

        raise ValueError(
            f"Missing Patreon team mappings: {missing[:10]}"
        )

    frame["team_id"] = frame["team_id"].astype(int)

    return frame


def get_existing_mapping(
    connection: sqlite3.Connection,
    source_player_id: str,
) -> str | None:
    """Reuse a previously approved mapping for the source player."""

    rows = connection.execute(
        """
        SELECT DISTINCT player_id
        FROM player_source_mappings
        WHERE source_name = ?
          AND source_player_id = ?
        """,
        (
            SOURCE_NAME,
            source_player_id,
        ),
    ).fetchall()

    if len(rows) == 1:
        return str(rows[0][0])

    return None


def find_player_match(
    connection: sqlite3.Connection,
    *,
    player_name: str,
    season: int,
    team_id: int,
) -> tuple[str | None, str | None, float, str]:
    """Find the best canonical player candidate.

    Returns:
        player_id
        canonical player name
        similarity score
        match method
    """

    candidates = pd.read_sql_query(
        """
        SELECT DISTINCT
            player_id,
            player_name
        FROM players
        WHERE season = ?
          AND team_id = ?
        """,
        connection,
        params=(
            season,
            team_id,
        ),
    )

    if candidates.empty:
        return None, None, 0.0, "unmatched"

    target = normalise_name(player_name)

    candidates["normalised_name"] = (
        candidates["player_name"]
        .astype(str)
        .map(normalise_name)
    )

    exact = candidates[
        candidates["normalised_name"] == target
    ]

    # Only auto-accept an exact match if there is one
    # unambiguous canonical player.
    if exact["player_id"].nunique() == 1:
        row = exact.iloc[0]

        return (
            str(row["player_id"]),
            str(row["player_name"]),
            1.0,
            "exact",
        )

    # Everything fuzzy goes to review.
    candidates["score"] = candidates[
        "player_name"
    ].map(
        lambda candidate: similarity(
            player_name,
            str(candidate),
        )
    )

    candidates = candidates.sort_values(
        "score",
        ascending=False,
    )

    best = candidates.iloc[0]

    return (
        str(best["player_id"]),
        str(best["player_name"]),
        float(best["score"]),
        "fuzzy_review",
    )


def upsert_player_source_mapping(
    connection: sqlite3.Connection,
    *,
    player_id: str,
    source_player_id: str,
    season: int,
    team_id: int,
) -> None:
    """Persist an approved Patreon -> canonical player mapping."""

    connection.execute(
        """
        INSERT INTO player_source_mappings (
            player_id,
            source_name,
            source_player_id,
            season,
            team_id
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (
            source_name,
            source_player_id,
            season,
            team_id
        )
        DO UPDATE SET
            player_id = excluded.player_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            player_id,
            SOURCE_NAME,
            source_player_id,
            season,
            team_id,
        ),
    )


def upsert_review_row(
    connection: sqlite3.Connection,
    *,
    source_player_id: str,
    source_player_name: str,
    season: int,
    team_id: int,
    suggested_player_id: str | None,
    suggested_player_name: str | None,
    similarity_score: float,
) -> None:
    """Add an uncertain player match to the manual review queue."""

    connection.execute(
        """
        INSERT INTO player_mapping_review (
            source_name,
            source_player_id,
            source_player_name,
            season,
            team_id,
            suggested_player_id,
            suggested_player_name,
            similarity_score,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        ON CONFLICT (
            source_name,
            source_player_id,
            season,
            team_id
        )
        DO UPDATE SET
            source_player_name =
                excluded.source_player_name,
            suggested_player_id =
                excluded.suggested_player_id,
            suggested_player_name =
                excluded.suggested_player_name,
            similarity_score =
                excluded.similarity_score,
            updated_at = CURRENT_TIMESTAMP
        WHERE player_mapping_review.status = 'pending'
        """,
        (
            SOURCE_NAME,
            source_player_id,
            source_player_name,
            season,
            team_id,
            suggested_player_id,
            suggested_player_name,
            similarity_score,
        ),
    )


def build_player_mappings(
    connection: sqlite3.Connection,
) -> tuple[int, int, int]:
    """Build Patreon player mappings.

    Exact matches are persisted automatically.
    Fuzzy/unmatched players are queued for manual review.
    """

    raw = load_patreon_players()

    frame = attach_fixture_metadata(
        raw,
    )

    frame = attach_team_ids(
        connection,
        frame,
    )

    # We only need one row per player/team/season.
    players = (
        frame[
            [
                "source_player_id",
                "player_name",
                "season",
                "team_id",
            ]
        ]
        .drop_duplicates()
        .sort_values(
            [
                "season",
                "team_id",
                "player_name",
            ]
        )
    )

    exact_count = 0
    reused_count = 0
    review_count = 0

    for row in players.itertuples(index=False):
        source_player_id = str(
            row.source_player_id
        )

        season = int(row.season)
        team_id = int(row.team_id)
        player_name = str(row.player_name)

        # -----------------------------------------
        # Previously approved source ID.
        # -----------------------------------------
        existing_player_id = get_existing_mapping(
            connection,
            source_player_id,
        )

        if existing_player_id is not None:
            upsert_player_source_mapping(
                connection,
                player_id=existing_player_id,
                source_player_id=source_player_id,
                season=season,
                team_id=team_id,
            )

            reused_count += 1
            continue

        # -----------------------------------------
        # Try exact / fuzzy candidate matching.
        # -----------------------------------------
        (
            player_id,
            canonical_name,
            score,
            match_method,
        ) = find_player_match(
            connection,
            player_name=player_name,
            season=season,
            team_id=team_id,
        )

        if match_method == "exact":
            upsert_player_source_mapping(
                connection,
                player_id=player_id,
                source_player_id=source_player_id,
                season=season,
                team_id=team_id,
            )

            exact_count += 1
            continue

        # -----------------------------------------
        # Fuzzy and unmatched both need approval.
        # -----------------------------------------
        upsert_review_row(
            connection,
            source_player_id=source_player_id,
            source_player_name=player_name,
            season=season,
            team_id=team_id,
            suggested_player_id=player_id,
            suggested_player_name=canonical_name,
            similarity_score=score,
        )

        review_count += 1

    return (
        exact_count,
        reused_count,
        review_count,
    )


def main() -> None:
    with sqlite3.connect(
        DATABASE_PATH
    ) as connection:
        (
            exact_count,
            reused_count,
            review_count,
        ) = build_player_mappings(
            connection
        )

        connection.commit()

    print()
    print("Patreon player mapping complete.")
    print(
        f"Exact mappings:     {exact_count}"
    )
    print(
        f"Existing reused:    {reused_count}"
    )
    print(
        f"Needs review:       {review_count}"
    )


if __name__ == "__main__":
    main()