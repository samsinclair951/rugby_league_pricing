from __future__ import annotations

import base64
import re
from pathlib import Path

import streamlit as st

from dashboard.data import (
    load_fixture,
    load_last_results,
    load_latest_historical_matrix,
    load_upcoming_fixtures,
)
from dashboard.formatting import fixture_date_heading, short_result_rows, signed_line
from dashboard.pricing import price_fixture


ASSETS_DIR = Path(__file__).resolve().parent / "assets"
TEAM_LOGOS_DIR = ASSETS_DIR / "teams"
STEEDEN_BALL_PATH = ASSETS_DIR / "steeden_ball.png"
SUPER_LEAGUE_LOGO_PATH = ASSETS_DIR / "super_league_logo.png"
HERO_IMAGE_PATH = ASSETS_DIR / "hero_players.jpg"


def _page_icon() -> str:
    return str(STEEDEN_BALL_PATH) if STEEDEN_BALL_PATH.exists() else "🏉"


st.set_page_config(
    page_title="RL Pricing",
    page_icon=_page_icon(),
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


@st.cache_data(show_spinner=False)
def _image_data_uri(path: str, modified_ns: int) -> str:
    image_path = Path(path)
    suffix = image_path.suffix.lower()

    mime_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream")

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _asset_data_uri(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    return _image_data_uri(str(path), path.stat().st_mtime_ns)


def _team_logo_path(team_name: str) -> Path | None:
    slug = re.sub(r"[^a-z0-9]+", "_", team_name.strip().lower()).strip("_")

    for extension in ("png", "webp", "jpg", "jpeg", "svg"):
        candidate = TEAM_LOGOS_DIR / f"{slug}.{extension}"
        if candidate.exists():
            return candidate

    return None


def _inject_brand_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at 20% 10%, #ffeee0 0%, #fff8ef 30%, transparent 55%),
                radial-gradient(circle at 90% 5%, #d7f0ff 0%, #f5fbff 25%, transparent 45%),
                #fcfaf7;
        }

        .rl_pricing-hero {
            border-radius: 18px;
            overflow: hidden;
            border: 1px solid #d6d1c7;
            background: linear-gradient(135deg, #0a2836 0%, #254e68 40%, #d95f28 100%);
            color: #fff;
            margin-bottom: 1rem;
        }

        .rl_pricing-hero img {
            display: block;
            width: 100%;
            max-height: 360px;
            object-fit: cover;
            filter: saturate(1.05) contrast(1.05);
        }

        .rl_pricing-hero-copy {
            padding: 1rem 1.2rem 1.1rem;
        }

        .rl_pricing-kicker {
            letter-spacing: 0.08em;
            font-size: 0.75rem;
            text-transform: uppercase;
            font-weight: 700;
            opacity: 0.92;
            margin-bottom: 0.3rem;
        }

        .rl_pricing-heading {
            font-size: 2rem;
            font-weight: 800;
            margin: 0;
            line-height: 1.1;
        }

        .rl_pricing-sub {
            margin-top: 0.35rem;
            margin-bottom: 0;
            font-size: 1rem;
            opacity: 0.95;
        }

        .rl_pricing-loader {
            display: flex;
            align-items: center;
            gap: 0.8rem;
            padding: 0.6rem 0.9rem;
            margin: 0.4rem 0 0.7rem;
            border-radius: 12px;
            background: #f5f7f9;
            border: 1px solid #d2dae2;
            color: #274356;
            font-weight: 600;
        }

        .rl_pricing-loader img {
            width: 28px;
            height: 28px;
            border-radius: 50%;
            animation: rl_pricing-spin 1.1s linear infinite;
        }

        .team-fallback {
            width: 54px;
            height: 54px;
            border-radius: 50%;
            background: linear-gradient(145deg, #f0e7da, #e0d2bc);
            border: 1px solid #d0c4b2;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.86rem;
            font-weight: 800;
            color: #3f3528;
            margin-top: 0.1rem;
        }

        @keyframes rl_pricing-spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_brand_header() -> None:
    super_league_uri = _asset_data_uri(SUPER_LEAGUE_LOGO_PATH)
    hero_uri = _asset_data_uri(HERO_IMAGE_PATH)

    left_col, right_col = st.columns([4, 1])

    with left_col:
        if hero_uri:
            st.markdown(
                f"""
                <div class="rl_pricing-hero">
                    <img src="{hero_uri}" alt="rl_pricing hero" />
                    <div class="rl_pricing-hero-copy">
                        <div class="rl_pricing-kicker">Rugby League Model Hub</div>
                        <h1 class="rl_pricing-heading">Rugby Super League Pricing Dash</h1>
                        <p class="rl_pricing-sub">Upcoming fixtures, fair prices, and market-ready score distributions.</p>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div class="rl_pricing-hero">
                    <div class="rl_pricing-hero-copy" style="padding: 1.6rem 1.4rem 1.8rem;">
                        <div class="rl_pricing-kicker">Rugby League Model Hub</div>
                        <h1 class="rl_pricing-heading">Rugby Super League Pricing Dash</h1>
                        <p class="rl_pricing-sub">Add app/assets/hero_players.jpg to use a custom opening image.</p>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with right_col:
        if super_league_uri:
            st.image(super_league_uri, width=150)
        else:
            st.caption("Add app/assets/super_league_logo.png for league branding")


def _render_team_badge(team_name: str, size: int = 54) -> None:
    initials = "".join(part[0] for part in team_name.split()[:2]).upper()

    logo_path = _team_logo_path(team_name)
    if logo_path is not None:
        try:
            st.image(str(logo_path), width=size)
            return
        except Exception:
            # Bad or unsupported image files should not break the app.
            pass

    st.markdown(
        f"<div class='team-fallback'>{initials}</div>",
        unsafe_allow_html=True,
    )


def _start_loader(message: str):
    placeholder = st.empty()
    steeden_uri = _asset_data_uri(STEEDEN_BALL_PATH)

    if steeden_uri:
        placeholder.markdown(
            f"""
            <div class="rl_pricing-loader">
                <img src="{steeden_uri}" alt="Loading" />
                <span>{message}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        placeholder.info(message)

    return placeholder


def show_fixture_list() -> None:
    _inject_brand_styles()
    _render_brand_header()
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

            home_col, middle_col, away_col = st.columns([1, 7, 1])
            with home_col:
                _render_team_badge(fixture.home_team)
            with middle_col:
                if st.button(label, key=f"fixture-{fixture.fixture_id}", width="stretch"):
                    st.session_state["selected_fixture_id"] = fixture.fixture_id
                    st.rerun()
            with away_col:
                _render_team_badge(fixture.away_team)


def show_fixture_detail(fixture_id: str) -> None:
    _inject_brand_styles()
    _render_brand_header()

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
        _render_team_badge(fixture["home_team"], size=70)
        st.metric(fixture["home_team"], f"{expected_home:.1f}", "Expected points")
    with away_col:
        _render_team_badge(fixture["away_team"], size=70)
        st.metric(fixture["away_team"], f"{expected_away:.1f}", "Expected points")

    st.divider()
    st.subheader("Recent results")

    home_results = _last_results(int(fixture["home_team_id"]), fixture_date)
    away_results = _last_results(int(fixture["away_team_id"]), fixture_date)

    home_col, away_col = st.columns(2)
    with home_col:
        st.markdown(f"**{fixture['home_team']} - last 3**")
        st.dataframe(
            short_result_rows(home_results),
            hide_index=True,
            width="stretch",
        )
    with away_col:
        st.markdown(f"**{fixture['away_team']} - last 3**")
        st.dataframe(
            short_result_rows(away_results),
            hide_index=True,
            width="stretch",
        )

    loader = _start_loader("Spinning the Steeden and building fixture markets...")
    try:
        prices = price_fixture(
            historical_matrix=_historical_matrix(),
            expected_home_score=expected_home,
            expected_away_score=expected_away,
        )
    finally:
        loader.empty()

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
        width="stretch",
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
            width="stretch",
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
            width="stretch",
        )


selected_fixture_id = st.session_state.get("selected_fixture_id")

if selected_fixture_id:
    show_fixture_detail(selected_fixture_id)
else:
    show_fixture_list()
