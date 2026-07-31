# Rugby League Pricing

A Python project for collecting rugby league data and building a rugby league pricing model.

Current focus:

- Super League data ingestion
- SQLite data storage
- Feature engineering
- Team strength modelling
- Match pricing

## Requirements

- Python 3.12
- uv
- SQLite

## Setup

```bash
uv sync
```

## Initialising the database

```bash
uv run python scripts/initialise_database.py
```

## Loading historical data

Results

```bash
uv run python scripts/results/rugby_league_project/ingest_results.py \
  --start-season 2010 \
  --end-season 2026
```

Fixtures

```bash
uv run python scripts/fixtures/rugby_league_project/ingest_fixtures.py \
  --start-season 2010 \
  --end-season 2026
```

## Feature pipeline: results → base expected score

```mermaid
flowchart TD
    R[("results table<br/>(home_score, away_score)")]

    subgraph SF["scoring_factors package"]
        SF1["calculate_historical_scoring_factors()<br/>groups results by match_date,<br/>cumulative sum shifted by 1 day"]
        SF2["Output per fixture:<br/>league_average_points<br/>home_scoring_factor<br/>away_scoring_factor"]
        SF1 --> SF2
    end

    subgraph RF["recent_form package"]
        RF1["load_results() + stack_results()<br/>one row per team per match"]
        RF2["add_recent_form()<br/>rolling avg points_for / points_against<br/>over 5 and 10 game windows"]
        RF3[("recent_form table")]
        RF1 --> RF2 --> RF3
    end

    subgraph SM["strength_multipliers package"]
        SM1["add_league_average()<br/>rolling league avg points (50-game window)"]
        SM2["add_opponent_recent_form()<br/>attach opponent's rolling form"]
        SM3["add_raw_multipliers()<br/>shrink small samples to league avg,<br/>raw attack/defence multiplier"]
        SM4["iterate_strength_multipliers()<br/>loop: adjust performances for opponent<br/>quality, recompute, repeat until stable"]
        SM5[("strength_multipliers table<br/>attack_multiplier, defence_multiplier<br/>per team per fixture")]
        RF3 --> SM1 --> SM2 --> SM3 --> SM4 --> SM5
    end

    subgraph ES["expected_scores package"]
        ES1["_build_strength_features()<br/>pivot home/away rows into one row per fixture"]
        ES2["_prepare_scoring_factors()<br/>drop first-date NaNs"]
        ES3["calculate_expected_scores()<br/>see formula below"]
        ES4[("expected_scores table<br/>expected_home_score, expected_away_score,<br/>expected_margin, expected_total")]
        SM5 --> ES1
        R --> SF1
        R --> RF1
        SF2 --> ES2
        ES1 --> ES3
        ES2 --> ES3
        ES3 --> ES4
    end
```

Expected points formula (in [core.py](src/rugby_league_pricing/features/expected_scores/core.py)):

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

Each expected score combines three independent signals: the league baseline, opponent-adjusted team strength (from `strength_multipliers`), and the venue scoring factor (from `scoring_factors`).

### Home/away scoring factors are the home-advantage effect

`home_scoring_factor` and `away_scoring_factor` are calculated purely from venue (home vs away), not per-team — every fixture on the same date receives the identical factor regardless of which two teams are playing. They capture the league-wide tendency for home teams to score more than away teams. Team-specific strength (who's actually good or bad at attack/defence) is handled separately by the opponent-adjusted `attack_multiplier`/`defence_multiplier` in the `strength_multipliers` package.

## Project structure

```text
.
├── data/
├── scripts/
├── src/
├── tests/
├── pyproject.toml
└── README.md
```

## Current functionality

- Scrape historical results
- Scrape fixtures
- Maintain canonical team mappings
- Store data in SQLite
- Build recent-form & expected scores features

## Roadmap

- Match pricing model
- Days since previous game
- Weather/Seasonality
- Player ratings
- Team news analysis
- Dashboard