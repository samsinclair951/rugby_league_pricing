from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from rugby_league_pricing.database.connection import get_connection


def load_pending_reviews() -> pd.DataFrame:
    with get_connection() as connection:
        return pd.read_sql_query(
            """
            SELECT
                pmr.player_mapping_review_id,
                pmr.source_player_id,
                pmr.source_player_name,
                pmr.season,
                pmr.team_id,
                t.canonical_name AS team_name,
                pmr.suggested_player_id,
                pmr.suggested_player_name,
                pmr.similarity_score
            FROM player_mapping_review pmr
            JOIN teams t
                ON t.team_id = pmr.team_id
            WHERE pmr.status = 'pending'
            ORDER BY
                pmr.season DESC,
                t.canonical_name,
                pmr.source_player_name
            """,
            connection,
        )


def load_candidates(
    *,
    season: int,
    team_id: int,
) -> pd.DataFrame:
    with get_connection() as connection:
        return pd.read_sql_query(
            """
            SELECT DISTINCT
                player_id,
                player_name
            FROM players
            WHERE season = ?
              AND team_id = ?
            ORDER BY player_name
            """,
            connection,
            params=(
                season,
                team_id,
            ),
        )


def approve_mapping(
    *,
    review_id: int,
    player_id: str,
) -> None:
    with get_connection() as connection:
        review = connection.execute(
            """
            SELECT
                source_name,
                source_player_id
            FROM player_mapping_review
            WHERE player_mapping_review_id = ?
            """,
            (review_id,),
        ).fetchone()

        if review is None:
            raise ValueError(
                f"Review row {review_id} not found."
            )

        source_name, source_player_id = review

        pending_rows = connection.execute(
            """
            SELECT
                season,
                team_id
            FROM player_mapping_review
            WHERE source_name = ?
              AND source_player_id = ?
              AND status = 'pending'
            """,
            (
                source_name,
                source_player_id,
            ),
        ).fetchall()

        for season, team_id in pending_rows:
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
                    source_name,
                    source_player_id,
                    season,
                    team_id,
                ),
            )

        connection.execute(
            """
            UPDATE player_mapping_review
            SET
                suggested_player_id = ?,
                status = 'approved',
                updated_at = CURRENT_TIMESTAMP
            WHERE source_name = ?
              AND source_player_id = ?
              AND status = 'pending'
            """,
            (
                player_id,
                source_name,
                source_player_id,
            ),
        )

        connection.commit()


def reject_mapping(
    *,
    review_id: int,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE player_mapping_review
            SET
                status = 'rejected',
                updated_at = CURRENT_TIMESTAMP
            WHERE player_mapping_review_id = ?
            """,
            (review_id,),
        )

        connection.commit()


def show_player_mapping_review() -> None:
    st.header("Player Mapping Review")

    reviews = load_pending_reviews()

    if reviews.empty:
        st.success(
            "No player mappings need review."
        )
        return

    st.caption(
        f"{len(reviews)} mappings awaiting review"
    )

    for row in reviews.itertuples(
        index=False
    ):
        with st.expander(
            (
                f"{row.source_player_name} "
                f"· {row.team_name} "
                f"· {row.season}"
            ),
            expanded=False,
        ):
            st.write(
                f"**Patreon ID:** "
                f"{row.source_player_id}"
            )

            if row.suggested_player_id:
                st.write(
                    f"**Suggested:** "
                    f"{row.suggested_player_name} "
                    f"({row.suggested_player_id})"
                )

                st.write(
                    f"**Similarity:** "
                    f"{row.similarity_score:.1%}"
                )

            candidates = load_candidates(
                season=int(row.season),
                team_id=int(row.team_id),
            )

            options = {
                (
                    f"{candidate.player_name} "
                    f"({candidate.player_id})"
                ): candidate.player_id
                for candidate
                in candidates.itertuples(
                    index=False
                )
            }

            default_index = 0

            labels = list(options.keys())

            if (
                row.suggested_player_id
                and labels
            ):
                for i, label in enumerate(
                    labels
                ):
                    if (
                        options[label]
                        == row.suggested_player_id
                    ):
                        default_index = i
                        break

            selected_label = st.selectbox(
                "Canonical player",
                options=labels,
                index=default_index,
                key=(
                    f"player-map-"
                    f"{row.player_mapping_review_id}"
                ),
            )

            approve_col, reject_col = st.columns(
                2
            )

            with approve_col:
                if st.button(
                    "Approve",
                    key=(
                        f"approve-player-map-"
                        f"{row.player_mapping_review_id}"
                    ),
                    width="stretch",
                ):
                    approve_mapping(
                        review_id=(
                            row.player_mapping_review_id
                        ),
                        player_id=(
                            options[selected_label]
                        ),
                    )

                    st.rerun()

            with reject_col:
                if st.button(
                    "Reject",
                    key=(
                        f"reject-player-map-"
                        f"{row.player_mapping_review_id}"
                    ),
                    width="stretch",
                ):
                    reject_mapping(
                        review_id=(
                            row.player_mapping_review_id
                        ),
                    )

                    st.rerun()