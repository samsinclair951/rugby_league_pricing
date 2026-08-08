from __future__ import annotations

import streamlit as st

from dashboard.data import (
    load_fixture,
    load_last_results,
    load_latest_historical_matrix,
    load_upcoming_fixtures,
)
from dashboard.formatting import fixture_date_heading, short_result_rows, signed_line
from dashboard.pricing import price_fixture


st.set_page_config(
    page_title="Rugby League Pricing",
    page_icon="🏉",
    layout="wide",
)


@st.cache_data(ttl=60)
def _upcoming_fixtures():
    return load_upcoming_fixtures(days=7)


@st.cache_data(ttl=60)
def _fixture(fixture_id: str):
    return load_fixture(fixture_id)


@st.cache_data(ttl=60)
def _last_results(team_id: int, before_date):
    return load_last_results(team_id, before_date=before_date, limit=3)


@st.cache_resource
def _historical_matrix():
    return load_latest_historical_matrix()


def show_fixture_list() -> None:
    st.title("Rugby League Prices")
    st.caption("Upcoming fixtures with model expected scores")

    fixtures = _upcoming_fixtures()

    if fixtures.empty:
        st.info("No fixtures with expected scores were found in the next seven days.")
        return

    for match_date, day_fixtures in fixtures.groupby(fixtures["match_date"].dt.date):
        st.subheader(fixture_date_heading(day_fixtures.iloc[0]["match_date"]))

        for fixture in day_fixtures.itertuples(index=False):
            label = f"{fixture.home_team} vs {fixture.away_team}"
            if fixture.kick_off:
                label = f"{label}  ·  {fixture.kick_off}"

            if st.button(label, key=f"fixture-{fixture.fixture_id}", use_container_width=True):
                st.session_state["selected_fixture_id"] = fixture.fixture_id
                st.rerun()


def show_fixture_detail(fixture_id: str) -> None:
    if st.button("← Back to fixtures"):
        st.session_state.pop("selected_fixture_id", None)
        st.rerun()

    fixture = _fixture(fixture_id)
    fixture_date = fixture["match_date"].date()

    st.caption(fixture_date_heading(fixture["match_date"]))
    st.title(f"{fixture['home_team']} vs {fixture['away_team']}")

    expected_home = float(fixture["expected_home_score"])
    expected_away = float(fixture["expected_away_score"])

    home_col, away_col = st.columns(2)
    with home_col:
        st.metric(fixture["home_team"], f"{expected_home:.1f}", "Expected points")
    with away_col:
        st.metric(fixture["away_team"], f"{expected_away:.1f}", "Expected points")

    st.divider()
    st.subheader("Recent results")

    home_results = _last_results(int(fixture["home_team_id"]), fixture_date)
    away_results = _last_results(int(fixture["away_team_id"]), fixture_date)

    home_col, away_col = st.columns(2)
    with home_col:
        st.markdown(f"**{fixture['home_team']} — last 3**")
        st.dataframe(
            short_result_rows(home_results),
            hide_index=True,
            use_container_width=True,
        )
    with away_col:
        st.markdown(f"**{fixture['away_team']} — last 3**")
        st.dataframe(
            short_result_rows(away_results),
            hide_index=True,
            use_container_width=True,
        )

    prices = price_fixture(
        historical_matrix=_historical_matrix(),
        expected_home_score=expected_home,
        expected_away_score=expected_away,
    )

    st.divider()
    st.subheader("Match odds")

    match_odds = prices["match_odds"].copy()
    match_odds["Selection"] = match_odds["selection"].map(
        {
            "home": fixture["home_team"],
            "draw": "Draw",
            "away": fixture["away_team"],
        }
    )
    match_odds["Probability"] = match_odds["probability"].map(lambda value: f"{value:.1%}")
    match_odds["True Price"] = match_odds["decimal_price"].map(lambda value: f"{value:.2f}")

    st.dataframe(
        match_odds[["Selection", "Probability", "True Price"]],
        hide_index=True,
        use_container_width=True,
    )

    handicap_col, totals_col = st.columns(2)

    with handicap_col:
        st.subheader("Handicap")
        st.caption(
            f"Mainline: {fixture['home_team']} "
            f"{signed_line(float(prices['main_handicap']))}"
        )

        handicaps = prices["handicaps"].copy()
        handicaps["Line"] = handicaps["line"].map(signed_line)
        handicaps[f"{fixture['home_team']} price"] = handicaps["home_price"].map(
            lambda value: f"{value:.2f}"
        )
        handicaps[f"{fixture['away_team']} price"] = handicaps["away_price"].map(
            lambda value: f"{value:.2f}"
        )

        st.dataframe(
            handicaps[
                [
                    "Line",
                    f"{fixture['home_team']} price",
                    f"{fixture['away_team']} price",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )

    with totals_col:
        st.subheader("Totals")
        st.caption(f"Mainline: {float(prices['main_total']):.1f}")

        totals = prices["totals"].copy()
        totals["Line"] = totals["line"].map(lambda value: f"{value:.1f}")
        totals["Over"] = totals["over_price"].map(lambda value: f"{value:.2f}")
        totals["Under"] = totals["under_price"].map(lambda value: f"{value:.2f}")

        st.dataframe(
            totals[["Line", "Over", "Under"]],
            hide_index=True,
            use_container_width=True,
        )


selected_fixture_id = st.session_state.get("selected_fixture_id")

if selected_fixture_id:
    show_fixture_detail(selected_fixture_id)
else:
    show_fixture_list()
