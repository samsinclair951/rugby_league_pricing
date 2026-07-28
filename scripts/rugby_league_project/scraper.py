from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.rugbyleagueproject.org/seasons"


def season_url(season: int) -> str:
    return f"{BASE_URL}/super-league-{season}/results.html"


def scrape_season_page(season: int) -> Tag:
    url = season_url(season)

    LOGGER.info("Downloading %s", url)

    response = requests.get(
        url,
        timeout=30,
        headers={"User-Agent": ("Mozilla/5.0 RugbyLeaguePricing/1.0")},
    )
    response.raise_for_status()

    soup = BeautifulSoup(
        response.content,
        "html.parser",
    )

    content = soup.find(id="content")

    if content is None:
        raise ValueError(f"Could not find #content for season {season}")

    match_list = content.find(class_="list")

    if match_list is None or not isinstance(match_list, Tag):
        raise ValueError(f"Could not find match list for season {season}")

    return match_list


def parse_int(value: str) -> int | None:
    cleaned = value.replace(",", "").strip()

    if not cleaned:
        return None

    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_match_rows(
    match_list: Tag,
    season: int,
) -> list[dict[str, Any]]:
    """
    Parse every match row on the Rugby League Project page.

    Completed matches contain integer scores.

    Unplayed fixtures contain:
        home_score = None
        away_score = None
    """
    matches: list[dict[str, Any]] = []
    current_month: str | None = None

    for row in match_list.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]

        if len(cells) != 10:
            continue

        date_value = cells[0].strip()

        if any(character.isalpha() for character in date_value):
            date_parts = date_value.split()

            if len(date_parts) != 2:
                LOGGER.warning(
                    "Skipping unexpected date value: %r",
                    date_value,
                )
                continue

            current_month, day = date_parts

        else:
            if current_month is None:
                LOGGER.warning(
                    "Skipping date without known month: %r",
                    date_value,
                )
                continue

            day = date_value

        try:
            match_date = datetime.strptime(  # noqa: DTZ007
                f"{current_month} {day} {season}",
                "%b %d %Y",
            ).date()

        except ValueError:
            LOGGER.warning(
                "Could not parse date %r for season %s",
                date_value,
                season,
            )
            continue

        home_score = parse_int(cells[3])
        away_score = parse_int(cells[5])

        # A valid row should either have two scores or no scores.
        if (home_score is None) != (away_score is None):
            LOGGER.warning(
                "Skipping match with only one score: %s vs %s",
                cells[2],
                cells[4],
            )
            continue

        matches.append(
            {
                "season": season,
                "match_date": match_date.isoformat(),
                "kick_off": cells[1].strip() or None,
                "home_team_name": cells[2].strip(),
                "home_score": home_score,
                "away_team_name": cells[4].strip(),
                "away_score": away_score,
                "referee": cells[6].strip() or None,
                "venue": cells[7].strip() or None,
                "attendance": parse_int(cells[8]),
            }
        )

    LOGGER.info(
        "Season %s: parsed %s match rows",
        season,
        len(matches),
    )

    return matches


def scrape_season_matches(
    season: int,
) -> list[dict[str, Any]]:
    """
    Download and parse all matches for one season.
    """
    match_list = scrape_season_page(season)

    return parse_match_rows(
        match_list=match_list,
        season=season,
    )
