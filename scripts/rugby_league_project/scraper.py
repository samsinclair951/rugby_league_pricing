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
    Parse Super League match rows from the Rugby League Project season page.

    Rugby League Project mixes other competitions into the season results page,
    including Challenge Cup and World Club Challenge fixtures.

    Competition/round heading rows are therefore used to track whether the
    following match rows belong to Super League.
    """
    matches: list[dict[str, Any]] = []

    current_month: str | None = None
    in_super_league_section = False

    seen_source_match_ids: set[str] = set()

    super_league_prefix = (
        f"/seasons/super-league-{season}/"
    )

    for row in match_list.find_all("tr"):
        cells = [
            cell.get_text(
                " ",
                strip=True,
            )
            for cell in row.find_all("td")
        ]

        # Heading rows determine which competition the following matches
        # belong to.
        if len(cells) != 10:
            links = row.find_all(
                "a",
                href=True,
            )

            for link in links:
                href = str(
                    link["href"]
                )

                if href.startswith(
                    "/competitions/"
                ):
                    in_super_league_section = False
                    break

                if href.startswith(
                    super_league_prefix
                ):
                    in_super_league_section = True
                    break

            continue

        # Ignore match rows belonging to Challenge Cup, WCC, etc.
        if not in_super_league_section:
            continue

        date_value = cells[0].strip()

        if any(
            character.isalpha()
            for character in date_value
        ):
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

        home_score = parse_int(
            cells[3]
        )

        away_score = parse_int(
            cells[5]
        )

        if (
            (home_score is None)
            != (away_score is None)
        ):
            LOGGER.warning(
                "Skipping match with only one score: %s vs %s",
                cells[2],
                cells[4],
            )
            continue

        if (
            season < datetime.now().year
            and home_score is None
            and away_score is None
        ):
            LOGGER.info(
                "Skipping unplayed fixture from historical season: %s vs %s",
                cells[2],
                cells[4],
            )
            continue

        source_match_id: str | None = None

        for link in row.find_all(
            "a",
            href=True,
        ):
            href = str(
                link["href"]
            )

            if href.startswith(
                "/matches/"
            ):
                source_match_id = (
                    href.rstrip("/")
                    .split("/")[-1]
                )
                break

        # RLP can expose a rearranged fixture more than once on the page.
        # The numeric match ID is the safest dedupe key.
        if (
            source_match_id is not None
            and source_match_id
            in seen_source_match_ids
        ):
            LOGGER.info(
                "Skipping duplicate RLP match %s: %s vs %s",
                source_match_id,
                cells[2],
                cells[4],
            )
            continue

        if source_match_id is not None:
            seen_source_match_ids.add(
                source_match_id
            )

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
                "attendance": parse_int(
                    cells[8]
                ),
                "source_match_id": source_match_id,
            }
        )

    LOGGER.info(
        "Season %s: parsed %s Super League match rows",
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
