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
- Build recent-form features

## Roadmap

- Days since previous game
- Opponent-adjusted form
- Team ratings
- Player ratings
- Match pricing model
- Dashboard