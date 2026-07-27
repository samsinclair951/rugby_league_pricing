"""Scrape Super League results and upsert them into SQLite.

Place this file at:
    scripts/ingest_results.py

Run from the repository root:
    uv run python scripts/ingest_results.py
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from datetime import datetime
from typing import Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup

from rugby_league_pricing.database.connection import get_connection


BASE_URL = "https://www.rugbyleagueproject.org"

SEASON_SUFFIXES: dict[int, str] = {
    2012: "xvii-2012",
    2013: "xviii-2013",
    2014: "xix-2014",
    2015: "xx-2015",
    2016: "xxi-2016",
    2017: "xxii-2017",
    2018: "xxiii-2018",
    2019: "xxiv-2019",
    2020: "xxv-2020",
    2021: "xxvi-2021",
    2022: "xxvii-2022",
    2023: "xxviii-2023",
    2024: "xxix-2024",
    2025: "xxx-2025",
    2026: "xxxi-2026",
}

LOGGER = logging.getLogger("results_ingestion")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split()).strip()


def parse_score(value: str) -> int | None:
    value = clean_text(value)
    if not value or value in {"-", "–", "—", "TBC"}:
        return None

    try:
        return int(value)
    except ValueError:
        LOGGER.warning("Could not parse score value: %r", value)
        return None


def parse_match_date(date_text: str, season: int) -> str:
    """Return an ISO date suitable for SQLite.

    The source has used slightly different date formats over time, so several
    formats are attempted before falling back to pandas.
    """
    date_text = clean_text(date_text)

    candidate_values = [date_text]
    if str(season) not in date_text:
        candidate_values.append(f"{date_text} {season}")

    formats = (
        "%d %b %Y",
        "%d %B %Y",
        "%a %d %b %Y",
        "%a %d %B %Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
    )

    for candidate in candidate_values:
        for date_format in formats:
            try:
                return datetime.strptime(candidate, date_format).date().isoformat()
            except ValueError:
                continue

    parsed = pd.to_datetime(candidate_values[-1], dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(
            f"Could not parse match date {date_text!r} for season {season}"
        )

    return parsed.date().isoformat()


def season_url(season: int) -> str:
    try:
        suffix = SEASON_SUFFIXES[season]
    except KeyError as exc:
        raise ValueError(f"No Rugby League Project suffix configured for {season}") from exc

    return f"{BASE_URL}/seasons/super-league-{suffix}/results.html"


def fetch_season_page(
    season: int,
    session: requests.Session,
    timeout: int = 30,
) -> BeautifulSoup:
    url = season_url(season)
    LOGGER.info("Fetching season=%s url=%s", season, url)

    response = session.get(url, timeout=timeout)
    response.raise_for_status()

    return BeautifulSoup(response.content, "html.parser")


def extract_fixture_rows(
    soup: BeautifulSoup,
    season: int,
) -> list[dict[str, object]]:
    content = soup.find(id="content")

    if content is None:
        raise ValueError("Could not find page element with id='content'")

    results_list = content.find(class_="list")

    if results_list is None:
        raise ValueError("Could not find results element with class='list'")

    all_cells = results_list.find_all("td")

    # The first 11 cells are headings/navigation rather than a fixture.
    fixture_cells = all_cells[11:]

    columns_per_fixture = 11

    if len(fixture_cells) < columns_per_fixture:
        raise ValueError(
            f"Not enough fixture cells found for season {season}: "
            f"{len(fixture_cells)}"
        )

    fixtures: list[dict[str, object]] = []

    for index in range(0, len(fixture_cells), columns_per_fixture):
        cells = fixture_cells[index:index + columns_per_fixture]

        if len(cells) != columns_per_fixture:
            LOGGER.warning(
                "Skipping incomplete fixture row season=%s cells=%s",
                season,
                len(cells),
            )
            continue

        values = [
            clean_text(cell.get_text(" ", strip=True))
            for cell in cells
        ]

        round_name = values[1]
        date_text = values[2]
        home_team = values[4]
        home_score = parse_score(values[5])
        away_team = values[6]
        away_score = parse_score(values[7])
        venue = values[9]

        if not home_team or not away_team:
            continue

        try:
            match_date = parse_match_date(date_text, season)
        except ValueError as exc:
            LOGGER.warning(
                "Skipping fixture season=%s home=%r away=%r: %s",
                season,
                home_team,
                away_team,
                exc,
            )
            continue

        status = (
            "completed"
            if home_score is not None and away_score is not None
            else "scheduled"
        )

        fixtures.append(
            {
                "competition": "Super League",
                "season": season,
                "round": round_name or None,
                "match_date": match_date,
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home_score,
                "away_score": away_score,
                "venue": venue or None,
                "status": status,
            }
        )

    if not fixtures:
        raise ValueError(f"No fixture rows found for season {season}")

    LOGGER.info(
        "Parsed season=%s fixtures=%s",
        season,
        len(fixtures),
    )

    return fixtures

def scrape_season(
    season: int,
    session: requests.Session,
) -> pd.DataFrame:
    soup = fetch_season_page(season, session)
    rows = extract_fixture_rows(soup, season)

    return pd.DataFrame(
        rows,
        columns=[
            "competition",
            "season",
            "round",
            "match_date",
            "home_team",
            "away_team",
            "home_score",
            "away_score",
            "venue",
            "status",
        ],
    )


def validate_fixtures(fixtures: pd.DataFrame) -> None:
    required_columns = {
        "competition",
        "season",
        "match_date",
        "home_team",
        "away_team",
        "status",
    }
    missing = required_columns.difference(fixtures.columns)
    if missing:
        raise ValueError(f"Missing required fixture columns: {sorted(missing)}")

    if fixtures.empty:
        raise ValueError("No fixtures were scraped")

    if fixtures[list(required_columns)].isna().any().any():
        raise ValueError("Required fixture fields contain null values")

    duplicate_count = fixtures.duplicated(
        subset=["match_date", "home_team", "away_team"]
    ).sum()
    if duplicate_count:
        LOGGER.warning("Dropping duplicate scraped fixtures=%s", duplicate_count)


def upsert_fixtures(
    connection: sqlite3.Connection,
    fixtures: pd.DataFrame,
) -> int:
    fixtures = fixtures.drop_duplicates(
        subset=["match_date", "home_team", "away_team"],
        keep="last",
    )

    sql = """
        INSERT INTO fixtures (
            competition,
            season,
            round,
            match_date,
            home_team,
            away_team,
            home_score,
            away_score,
            venue,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(match_date, home_team, away_team)
        DO UPDATE SET
            competition = excluded.competition,
            season = excluded.season,
            round = excluded.round,
            home_score = excluded.home_score,
            away_score = excluded.away_score,
            venue = excluded.venue,
            status = excluded.status
    """

    records = [
        (
            row.competition,
            int(row.season),
            row.round,
            row.match_date,
            row.home_team,
            row.away_team,
            None if pd.isna(row.home_score) else int(row.home_score),
            None if pd.isna(row.away_score) else int(row.away_score),
            row.venue,
            row.status,
        )
        for row in fixtures.itertuples(index=False)
    ]

    connection.executemany(sql, records)
    return len(records)


def ingest_results(
    seasons: Iterable[int],
    request_delay_seconds: float = 0.5,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    with requests.Session() as session:
        session.headers.update(
            {
                "User-Agent": (
                    "rugby-league-pricing/0.1 "
                    "(historical results ingestion; personal analytics project)"
                )
            }
        )

        for season in seasons:
            try:
                frames.append(scrape_season(season, session))
            except (requests.RequestException, ValueError) as exc:
                LOGGER.error("Season ingestion failed season=%s error=%s", season, exc)
                continue

            time.sleep(request_delay_seconds)

    if not frames:
        raise RuntimeError("No seasons were scraped successfully")

    fixtures = pd.concat(frames, ignore_index=True)
    validate_fixtures(fixtures)

    with get_connection() as connection:
        processed = upsert_fixtures(connection, fixtures)

    LOGGER.info(
        "Results ingestion complete seasons=%s rows_processed=%s",
        sorted(fixtures["season"].unique().tolist()),
        processed,
    )
    return fixtures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Super League results into the fixtures table."
    )
    parser.add_argument(
        "--start-season",
        type=int,
        default=min(SEASON_SUFFIXES),
    )
    parser.add_argument(
        "--end-season",
        type=int,
        default=max(SEASON_SUFFIXES),
    )
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()

    if args.start_season > args.end_season:
        raise ValueError("--start-season cannot be later than --end-season")

    seasons = range(args.start_season, args.end_season + 1)
    fixtures = ingest_results(seasons)

    LOGGER.info(
        "Latest scraped fixtures:\n%s",
        fixtures.sort_values("match_date", ascending=False).head(10).to_string(
            index=False
        ),
    )


if __name__ == "__main__":
    main()
