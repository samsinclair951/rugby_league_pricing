from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag


LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.rugbyleagueproject.org/seasons"

COMPETITIONS: dict[str, dict[str, str]] = {
    "super_league": {
        "slug": "super-league",
        "tournament_name": "Super League",
        "country": "England",
    },
    "nrl": {
        "slug": "nrl",
        "tournament_name": "NRL",
        "country": "Australia",
    },
}


def get_competition_config(
    competition: str,
) -> dict[str, str]:
    """Return configuration for a supported competition."""

    try:
        return COMPETITIONS[competition]
    except KeyError as exc:
        raise ValueError(
            f"Unknown competition {competition!r}. "
            f"Expected one of {sorted(COMPETITIONS)}"
        ) from exc


def season_url(
    season: int,
    competition: str = "super_league",
) -> str:
    """Build the Rugby League Project results URL."""

    config = get_competition_config(
        competition
    )

    return (
        f"{BASE_URL}/"
        f"{config['slug']}-{season}/"
        "results.html"
    )


def scrape_season_page(
    season: int,
    competition: str = "super_league",
) -> Tag:
    """Download one RLP season results page."""

    url = season_url(
        season=season,
        competition=competition,
    )

    LOGGER.info(
        "Downloading %s",
        url,
    )

    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "RugbyLeaguePricing/1.0"
            )
        },
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.content,
        "html.parser",
    )

    content = soup.find(
        id="content"
    )

    if content is None:
        raise ValueError(
            "Could not find #content for "
            f"{competition} season {season}"
        )

    match_list = content.find(
        class_="list"
    )

    if (
        match_list is None
        or not isinstance(
            match_list,
            Tag,
        )
    ):
        raise ValueError(
            "Could not find match list for "
            f"{competition} season {season}"
        )

    return match_list


def parse_int(
    value: str,
) -> int | None:
    """Parse an integer from an RLP table value."""

    cleaned = (
        value
        .replace(",", "")
        .strip()
    )

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
    Convert Rugby League Project section headings into
    canonical competition stages.

    Returns None for headings which should not be treated
    as part of the league competition.
    """

    value = " ".join(
        heading_text.lower().split()
    )

    # Other competitions which may appear among league
    # fixtures on Rugby League Project.
    if "challenge cup" in value:
        return None

    if "world club challenge" in value:
        return None

    if "world club series" in value:
        return None

    if (
        "qualifier" in value
        and "qualif playoff" not in value
    ):
        return None

    if "million pound game" in value:
        return None

    if "kiwis tour" in value:
        return None

    # Super League Super 8s era.
    if value.startswith("s8 round"):
        return "super_8s"

    # Normal league rounds.
    if value.startswith("round "):
        return "regular_season"

    # Finals.
    if "grand final" in value:
        return "grand_final"

    if value in {
        "quarter final",
        "quarter-final",
    }:
        return "quarter_final"

    if value in {
        "qualif final",
        "qualifying final",
    }:
        return "qualifying_final"

    if value in {
        "semi final",
        "semi-final",
        "prelim semi",
        "qualif semi",
    }:
        return "semi_final"

    if value in {
        "prelim final",
        "preliminary final",
    }:
        return "preliminary_final"

    if value in {
        "elim",
        "elim final",
        "elimination final",
    }:
        return "elimination_final"

    if value == "qualif playoff":
        return "playoff"

    return None


def parse_match_rows(
    match_list: Tag,
    season: int,
    competition: str = "super_league",
) -> list[dict[str, Any]]:
    """
    Parse league match rows from an RLP season page.

    RLP uses slightly different row layouts between
    competitions. In particular, NRL rows include an
    initial competition-name column.
    """

    config = get_competition_config(
        competition
    )

    tournament_name = config["tournament_name"]
    competition_slug = config["slug"]

    matches: list[dict[str, Any]] = []

    current_month: str | None = None
    current_stage: str | None = None

    seen_source_match_ids: set[str] = set()

    competition_prefix = (
        f"/seasons/{competition_slug}-{season}/"
    )

    for row in match_list.find_all("tr"):
        cells = [
            cell.get_text(
                " ",
                strip=True,
            )
            for cell in row.find_all("td")
        ]

        # Match rows have at least the standard
        # date/time/team/score/referee/venue/attendance
        # columns.
        #
        # Heading rows contain fewer cells.
        if len(cells) < 9:
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

            is_competition_heading = any(
                str(
                    link["href"]
                ).startswith(
                    competition_prefix
                )
                for link in links
            )

            is_other_competition = any(
                str(
                    link["href"]
                ).startswith(
                    "/competitions/"
                )
                for link in links
            )

            normalised_stage = (
                normalise_competition_stage(
                    heading_text
                )
            )

            # First prioritise headings belonging
            # explicitly to this competition.
            if is_competition_heading:
                current_stage = (
                    normalised_stage
                )
                continue

            # Explicitly linked other competition,
            # e.g. Challenge Cup / WCC.
            if is_other_competition:
                current_stage = None
                continue

            # Some genuine league/finals headings
            # have no useful competition link.
            if normalised_stage is not None:
                current_stage = (
                    normalised_stage
                )
                continue

            continue

        # Ignore matches while inside another
        # competition section.
        if current_stage is None:
            continue

        match_cells = cells

        # NRL result rows contain an extra first column:
        #
        # NRL Premiership 2024 | Mar 2 | Sat 6:30pm |
        # Manly | 36 | South Sydney | 24 | ...
        #
        # Super League does not have this column.
        first_cell = (
            match_cells[0]
            .strip()
        )

        first_parts = (
            first_cell.split()
        )

        first_cell_is_date = (
            first_cell.isdigit()
            or (
                len(first_parts) == 2
                and any(
                    character.isalpha()
                    for character
                    in first_cell
                )
            )
        )

        if not first_cell_is_date:
            match_cells = (
                match_cells[1:]
            )

        if len(match_cells) < 9:
            LOGGER.warning(
                "Skipping unexpected match row: %r",
                cells,
            )
            continue

        date_value = (
            match_cells[0].strip()
        )

        if any(
            character.isalpha()
            for character
            in date_value
        ):
            date_parts = (
                date_value.split()
            )

            if len(date_parts) != 2:
                LOGGER.warning(
                    "Skipping unexpected "
                    "date value: %r",
                    date_value,
                )
                continue

            current_month, day = (
                date_parts
            )

        else:
            if current_month is None:
                LOGGER.warning(
                    "Skipping date without "
                    "known month: %r",
                    date_value,
                )
                continue

            day = date_value

        try:
            match_date = datetime.strptime(  # noqa: DTZ007
                (
                    f"{current_month} "
                    f"{day} "
                    f"{season}"
                ),
                "%b %d %Y",
            ).date()

        except ValueError:
            LOGGER.warning(
                "Could not parse date %r "
                "for season %s",
                date_value,
                season,
            )
            continue

        home_score = parse_int(
            match_cells[3]
        )

        away_score = parse_int(
            match_cells[5]
        )

        if (
            (home_score is None)
            != (away_score is None)
        ):
            LOGGER.warning(
                "Skipping match with only "
                "one score: %s vs %s",
                match_cells[2],
                match_cells[4],
            )
            continue

        if (
            season < datetime.now(UTC).year
            and home_score is None
            and away_score is None
        ):
            LOGGER.info(
                "Skipping unplayed fixture "
                "from historical season: "
                "%s vs %s",
                match_cells[2],
                match_cells[4],
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

        if (
            source_match_id is not None
            and source_match_id
            in seen_source_match_ids
        ):
            LOGGER.info(
                "Skipping duplicate RLP "
                "match %s: %s vs %s",
                source_match_id,
                match_cells[2],
                match_cells[4],
            )
            continue

        if source_match_id is not None:
            seen_source_match_ids.add(
                source_match_id
            )

        matches.append(
            {
                "season": season,
                "tournament_name": (
                    tournament_name
                ),
                "competition_stage_name": (
                    current_stage
                ),
                "match_date": (
                    match_date.isoformat()
                ),
                "kick_off": (
                    match_cells[1].strip()
                    or None
                ),
                "home_team_name": (
                    match_cells[2].strip()
                ),
                "home_score": (
                    home_score
                ),
                "away_team_name": (
                    match_cells[4].strip()
                ),
                "away_score": (
                    away_score
                ),
                "referee": (
                    match_cells[6].strip()
                    or None
                ),
                "venue": (
                    match_cells[7].strip()
                    or None
                ),
                "attendance": (
                    parse_int(
                        match_cells[8]
                    )
                ),
                "source_match_id": (
                    source_match_id
                ),
            }
        )

    LOGGER.info(
        "Season %s: parsed %s %s match rows",
        season,
        len(matches),
        tournament_name,
    )

    return matches

def scrape_season_matches(
    season: int,
    competition: str = "super_league",
) -> list[dict[str, Any]]:
    """
    Download and parse all requested competition
    matches for one season.
    """

    match_list = scrape_season_page(
        season=season,
        competition=competition,
    )

    return parse_match_rows(
        match_list=match_list,
        season=season,
        competition=competition,
    )


def inspect_section_headings(
    match_list: Tag,
) -> None:
    """
    Print non-match rows from an RLP results table.

    Useful for checking how RLP labels rounds and
    postseason stages.
    """

    for row in match_list.find_all(
        "tr"
    ):
        cells = row.find_all(
            "td"
        )

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
            for link
            in row.find_all(
                "a",
                href=True,
            )
        ]

        print(
            {
                "text": text,
                "links": links,
                "normalised_stage": (
                    normalise_competition_stage(
                        text
                    )
                ),
            }
        )