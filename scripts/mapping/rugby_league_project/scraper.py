from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.rugbyleagueproject.org/seasons"

TOURNAMENT_NAME = "Super League"


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


def normalise_competition_stage(
    heading_text: str,
) -> str | None:
    """
    Convert Rugby League Project section headings into canonical
    Super League competition stages.

    Return None for sections that should not be ingested as Super League.
    """
    value = " ".join(
        heading_text.lower().split()
    )

    if "challenge cup" in value:
        return None

    if "world club challenge" in value:
        return None

    if "world club series" in value:
        return None

    if "qualifier" in value and "qualif playoff" not in value:
        return None

    if "million pound game" in value:
        return None

    if "kiwis tour" in value:
        return None

    if value.startswith("s8 round"):
        return "super_8s"

    if "grand final" in value:
        return "grand_final"

    if value == "quarter final":
        return "quarter_final"

    if value in {
        "semi final",
        "prelim semi",
        "qualif semi",
    }:
        return "semi_final"

    if value == "prelim final":
        return "preliminary_final"

    if value == "elim":
        return "elimination_final"

    if value == "qualif playoff":
        return "playoff"

    if value.startswith("round "):
        return "regular_season"

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
    current_stage: str | None = None

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
            heading_text = " ".join(
                row.get_text(
                    " ",
                    strip=True,
                ).split()
            )
    
            links = row.find_all(
                "a",
                href=True,
            )
    
            is_super_league_heading = any(
                str(link["href"]).startswith(
                    super_league_prefix
                )
                for link in links
            )
    
            is_other_competition = any(
                str(link["href"]).startswith(
                    "/competitions/"
                )
                for link in links
            )
    
            if is_other_competition:
                current_stage = None
                continue

            normalised_stage = normalise_competition_stage(
                heading_text
            )

            if is_super_league_heading:
                current_stage = normalised_stage
                continue

            # Some genuine Super League postseason headings on RLP have no links,
            # for example S8 Round 1, Semi Final, Grand Final, Elim, etc.
            if normalised_stage is not None:
                current_stage = normalised_stage
                continue

            continue

        # Ignore match rows belonging to Challenge Cup, WCC, etc.
        if current_stage is None:
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
            season < datetime.now(UTC).year
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
                "tournament_name": TOURNAMENT_NAME,
                "competition_stage_name": current_stage,
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


def inspect_section_headings(
    match_list: Tag,
) -> None:
    for row in match_list.find_all("tr"):
        cells = row.find_all("td")

        if len(cells) == 10:
            continue

        text = " ".join(
            row.get_text(
                " ",
                strip=True,
            ).split()
        )

        if not text:
            continue

        links = [
            str(link["href"])
            for link in row.find_all(
                "a",
                href=True,
            )
        ]

        print(
            {
                "text": text,
                "links": links,
                "normalised_stage": normalise_competition_stage(
                    text
                ),
            }
        )