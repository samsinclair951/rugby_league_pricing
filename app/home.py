from pathlib import Path

import pandas as pd
import streamlit as st

from rugby_league_pricing.ratings.simple_tries_pred import (
    fit_poisson_model,
    load_results,
    predict_match,
    prepare_model_data,
)

st.set_page_config(
    page_title="Rugby League Pricing",
    page_icon="🏉",
    layout="wide",
)

DATA_PATH = Path("data/sample_results/slres_unstacked.csv")


@st.cache_data
def get_results():
    return load_results(DATA_PATH)


@st.cache_resource
def get_model(year: int):
    results = get_results()
    model_data = prepare_model_data(results, year)
    return fit_poisson_model(model_data)


st.title("🏉 Rugby League Match Predictor")

DEFAULT_BLEND_WEIGHTS = {
    "recent_form": 0.60,
    "player_strength": 0.30,
    "team_news": 0.10,
}


def normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return {key: 0.0 for key in weights}
    return {key: value / total for key, value in weights.items()}


st.sidebar.subheader("Adaptive blend controls")
st.sidebar.caption(
    "This keeps the recent-form strength as the anchor, then adds player-strength and team-news as corrective layers."
)

blend_weights = {}
blend_weights["recent_form"] = st.sidebar.slider(
    "Recent form weight",
    min_value=0.0,
    max_value=1.0,
    value=DEFAULT_BLEND_WEIGHTS["recent_form"],
    step=0.05,
)
blend_weights["player_strength"] = st.sidebar.slider(
    "Player strength weight",
    min_value=0.0,
    max_value=1.0,
    value=DEFAULT_BLEND_WEIGHTS["player_strength"],
    step=0.05,
)
blend_weights["team_news"] = st.sidebar.slider(
    "Team news weight",
    min_value=0.0,
    max_value=1.0,
    value=DEFAULT_BLEND_WEIGHTS["team_news"],
    step=0.05,
)

normalised_weights = normalise_weights(blend_weights)

st.sidebar.write("Current blend profile:")
st.sidebar.dataframe(
    pd.DataFrame(
        {
            "weight": list(normalised_weights.values()),
            "share": [f"{value:.0%}" for value in normalised_weights.values()],
        },
        index=list(normalised_weights.keys()),
    ),
    use_container_width=True,
)

st.sidebar.caption(
    "Base formula: expected_team_strength = recent_form × w_form + player_strength × w_player + team_news × w_news"
)

try:
    results = get_results()
except Exception as exc:
    st.error(f"Could not load results: {exc}")
    st.stop()

available_years = sorted(results["year"].unique(), reverse=True)

year = st.selectbox(
    "Season",
    options=available_years,
)

season_results = results.loc[results["year"].eq(year)]

teams = sorted(set(season_results["home"]).union(season_results["away"]))

col1, col2 = st.columns(2)

with col1:
    home_team = st.selectbox(
        "Home team",
        options=teams,
        index=teams.index("Wigan") if "Wigan" in teams else 0,
    )

with col2:
    away_options = [team for team in teams if team != home_team]

    default_away_index = (
        away_options.index("St Helens") if "St Helens" in away_options else 0
    )

    away_team = st.selectbox(
        "Away team",
        options=away_options,
        index=default_away_index,
    )

if st.button("Generate prediction", type="primary"):
    try:
        with st.spinner("Fitting model and generating prediction..."):
            model = get_model(year)

            prediction = predict_match(
                model=model,
                home_team=home_team,
                away_team=away_team,
            )

    except Exception as exc:
        st.error(f"Prediction failed: {exc}")
        st.stop()

    st.subheader(f"{home_team} vs {away_team}")

    metric1, metric2 = st.columns(2)

    metric1.metric(
        f"{home_team} expected tries",
        f"{prediction.expected_home_tries:.2f}",
    )

    metric2.metric(
        f"{away_team} expected tries",
        f"{prediction.expected_away_tries:.2f}",
    )

    st.subheader("Adaptive blend profile")

    blend_df = pd.DataFrame(
        {
            "weight": list(normalised_weights.values()),
            "share": [f"{value:.0%}" for value in normalised_weights.values()],
        },
        index=list(normalised_weights.keys()),
    )
    st.dataframe(blend_df, use_container_width=True)

    st.caption(
        "The default values are aligned with the current evidence: recent form remains the anchor, player strength adds a meaningful correction, and team news only acts as the final override."
    )

    st.subheader("Result probabilities")

    home_col, draw_col, away_col = st.columns(3)

    home_col.metric(
        f"{home_team} win",
        f"{prediction.home_win_probability:.1%}",
    )

    draw_col.metric(
        "Draw",
        f"{prediction.draw_probability:.1%}",
    )

    away_col.metric(
        f"{away_team} win",
        f"{prediction.away_win_probability:.1%}",
    )

    st.subheader("Tries probability matrix")

    st.dataframe(
        prediction.probability_matrix.style.format("{:.2%}"),
        use_container_width=True,
    )
