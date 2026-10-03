# Rugby League Pricing

A Python project for collecting rugby league data, building team-strength features, and pricing match markets from score probability matrices.

## Overview

The project now covers the full path from raw data to market prices:

- ingest Super League results and fixtures into SQLite
- build recent-form and strength-multiplier features
- generate expected scores and future predictions
- create historical and Poisson score matrices
- price match odds, handicaps and totals
- surface prices in a Streamlit dashboard

## Requirements

- Python 3.12
- uv
- SQLite

## Quick start

```bash
uv sync
```

## Initialise the database

```bash
uv run python scripts/initialise_database.py
```

## Ingest data

Results:

```bash
uv run python scripts/results/rugby_league_project/ingest_results.py \
  --start-season 2010 \
  --end-season 2026
```

Fixtures:

```bash
uv run python scripts/fixtures/rugby_league_project/ingest_fixtures.py \
  --start-season 2010 \
  --end-season 2026
```

## Rebuild feature tables

Recent form:

```bash
uv run python scripts/features/rebuild_recent_form.py
```

Strength multipliers:

```bash
uv run python scripts/features/rebuild_strength_multipliers.py
```

Expected scores:

```bash
uv run python scripts/features/rebuild_expected_scores.py
```

Future expected-score predictions:

```bash
uv run python scripts/features/rebuild_predicted_scores.py
```

## Build the historical score matrix

```bash
uv run python scripts/pricing/rebuild_historical_matrix.py
```

The pricing package exposes score-matrix utilities such as:

- `build_historical_scoring_matrix()`
- `build_poisson_score_matrix()`
- `build_blended_score_matrix()`
- `blend_score_matrices()`
- `poisson_probabilities()`

You can inspect the latest stored matrix with:

```bash
uv run python scripts/pricing/view_matrix.py
```

## Pricing flow

The current pricing workflow is:

1. load a fixture and its expected scores
2. generate a score probability matrix from historical and/or Poisson assumptions
3. price match odds, handicap and totals markets
4. display the fixture in the dashboard

The key pricing logic lives under `src/rugby_league_pricing/pricing/` and is consumed by the app layer.

## Dashboard

Launch the app from the repo root:

```bash
uv run streamlit run app/home.py
```

For dashboard-specific notes and assumptions, see [README_DASHBOARD.md](README_DASHBOARD.md).

## Expected-score model

The base expected-score logic combines league baseline, team strength, and venue effects:

```text
expected_home_points = league_average_points
                        × home_attack_multiplier
                        × away_defence_multiplier
                        × home_scoring_factor

expected_away_points = league_average_points
                        × away_attack_multiplier
                        × home_defence_multiplier
                        × away_scoring_factor
```

This is the same pattern described in the feature pipeline and is implemented in the expected-scores package.

## Project structure

```text
.
├── app/
│   ├── assets/
│   └── dashboard/
├── config/
├── data/
├── notebooks/
├── scripts/
│   ├── features/
│   ├── fixtures/
│   ├── pricing/
│   └── results/
├── src/
│   └── rugby_league_pricing/
│       ├── database/
│       ├── features/
│       ├── pricing/
│       └── utils/
├── tests/
├── CHANGELOG.md
├── README.md
├── README_DASHBOARD.md
├── pyproject.toml
└── LICENSE
```

## Current functionality

- scrape and store historical results and fixtures
- maintain canonical team mappings
- build recent form and team strength features
- persist expected scores and predictions to SQLite
- generate score probability matrices for pricing
- price match odds, handicap and totals
- show fixture pricing in a Streamlit dashboard

## Roadmap

- TPF analysis and adjs
- Days since previous game
- Weather/Seasonality
- Market Prices
- Check again the pricing distributions with updated expected scores

notes:
- remember to edit the rebuild_expected_team_lineups to take in dates rather than fixture_id or both?
- remove sqlite backtest from the PR
- tidy the player blend models and teamsheets adjustments so we can do a newer version of pre-preview-expected-lineup adj
- allow for 18th man ingest teamsheets
