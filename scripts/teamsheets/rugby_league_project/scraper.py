from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.rugbyleagueproject.org"
SOURCE_NAME = "rugby_league_project"

MONTH_PATTERN = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b",
    flags=re.IGNORECASE,
)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0 Safari/537.36"
        )
    }
)


@dataclass(frozen=True)
class MatchReference:
    season: int
    match_date_text: str
    home_team: str
    away_team: str
    summary_url: str
    source_match_id: str


def _normalise_text(
    value: str,
) -> str:
    return " ".join(
        value.split()
    ).strip()


def _normalise_player_name(
    player_name: str,
) -> str:
    player_name = _normalise_text(
        player_name
    )

    return re.sub(
        r"\s+\(c\)$",
        "",
        player_name,
        flags=re.IGNORECASE,
    ).strip()


def _source_player_id_from_href(
    href: str | None,
) -> str | None:
    if not href:
        return None

    match = re.search(
        r"/players/(\d+)",
        href,
    )

    if match:
        return match.group(1)

    return None


def _source_match_id_from_href(
    href: str | None,
) -> str | None:
    if not href:
        return None

    match = re.search(
        r"/matches/(\d+)",
        href,
    )

    if match:
        return match.group(1)

    return None


def _team_slug_from_href(
    href: str,
    season: int,
) -> str | None:
    pattern = (
        rf"^/seasons/super-league-{season}/"
        r"([^/]+)/summary\.html$"
    )

    match = re.match(
        pattern,
        href,
    )

    if not match:
        return None

    slug = match.group(1)

    if slug.startswith("round-"):
        return None

    return slug


def get_page(
    url: str,
    timeout: int = 30,
    max_retries: int = 5,
    sleep_after_success: bool = True,
) -> requests.Response:
    """
    Download one Rugby League Project page with retries and polite throttling.
    """
    for attempt in range(
        max_retries
    ):
        try:
            response = SESSION.get(
                url,
                timeout=timeout,
            )

            response.raise_for_status()

            if sleep_after_success:
                time.sleep(
                    random.uniform(
                        2.0,
                        4.0,
                    )
                )

            return response

        except requests.RequestException:
            if attempt == max_retries - 1:
                raise

            wait_seconds = (
                10 * (2 ** attempt)
            )

            LOGGER.warning(
                "Request failed for %s. "
                "Retrying in %ss...",
                url,
                wait_seconds,
            )

            time.sleep(
                wait_seconds
            )

    raise RuntimeError(
        f"Could not download page: {url}"
    )


def _extract_fixture_teams(
    row: Tag,
    season: int,
) -> tuple[
    str,
    str,
] | None:
    team_candidates: list[
        tuple[str, str]
    ] = []

    for anchor in row.find_all(
        "a",
        href=True,
    ):
        href = str(
            anchor["href"]
        )

        team_slug = _team_slug_from_href(
            href=href,
            season=season,
        )

        if team_slug is None:
            continue

        team_name = _normalise_text(
            anchor.get_text(
                " ",
                strip=True,
            )
        )

        if not team_name:
            continue

        candidate = (
            team_slug,
            team_name,
        )

        if candidate not in team_candidates:
            team_candidates.append(
                candidate
            )

    if len(team_candidates) != 2:
        return None

    return (
        team_candidates[0][1],
        team_candidates[1][1],
    )


def _raw_match_date_text(
    row: Tag,
) -> str:
    cells = row.find_all(
        "td"
    )

    if not cells:
        return ""

    return _normalise_text(
        cells[0].get_text(
            " ",
            strip=True,
        )
    )


def _normalise_match_date_text(
    raw_date: str,
    current_month: str | None,
) -> tuple[
    str,
    str | None,
]:
    """
    RLP prints the month only on the first match in a month.

    Example:
        Feb 16
        17
        17

    Becomes:
        Feb 16
        Feb 17
        Feb 17
    """
    raw_date = _normalise_text(
        raw_date
    )

    if not raw_date:
        return "", current_month

    month_match = MONTH_PATTERN.match(
        raw_date
    )

    if month_match:
        month = (
            month_match.group(1)
            .title()
        )

        return (
            raw_date,
            month,
        )

    if (
        current_month is not None
        and re.fullmatch(
            r"\d{1,2}",
            raw_date,
        )
    ):
        return (
            f"{current_month} {raw_date}",
            current_month,
        )

    return (
        raw_date,
        current_month,
    )


def _match_href(
    row: Tag,
) -> str | None:
    for anchor in row.find_all(
        "a",
        href=True,
    ):
        href = str(
            anchor["href"]
        )

        if re.fullmatch(
            r"/matches/\d+",
            href,
        ):
            return href

    return None


def scrape_season_match_references(
    season: int,
    timeout: int = 30,
) -> list[MatchReference]:
    """
    Discover Super League match detail pages for one season.

    Uses RLP's direct /matches/{id} URLs while keeping the v6 competition
    section logic to avoid obvious WCC / Challenge Cup rows.
    """
    season_url = (
        f"{BASE_URL}/seasons/"
        f"super-league-{season}/results.html"
    )

    try:
        response = get_page(
            url=season_url,
            timeout=timeout,
        )

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not download "
            f"Super League {season} results page"
        ) from exc

    soup = BeautifulSoup(
        response.content,
        "html.parser",
    )

    content = soup.find(
        id="content"
    )

    if content is None:
        raise RuntimeError(
            f"Could not find page content "
            f"for Super League {season}"
        )

    match_list = content.find(
        class_="list"
    )

    if match_list is None:
        raise RuntimeError(
            f"Could not find results list "
            f"for Super League {season}"
        )

    references: list[
        MatchReference
    ] = []

    seen_match_ids: set[str] = set()

    current_month: str | None = None

    for row in match_list.find_all(
        "tr"
    ):
        match_href = _match_href(
            row
        )

        if match_href is None:
            continue

        source_match_id = (
            _source_match_id_from_href(
                match_href
            )
        )

        if source_match_id is None:
            continue

        if source_match_id in seen_match_ids:
            continue

        teams = _extract_fixture_teams(
            row=row,
            season=season,
        )

        if teams is None:
            continue

        (
            home_team,
            away_team,
        ) = teams

        (
            match_date_text,
            current_month,
        ) = _normalise_match_date_text(
            raw_date=_raw_match_date_text(
                row
            ),
            current_month=current_month,
        )

        references.append(
            MatchReference(
                season=season,
                match_date_text=match_date_text,
                home_team=home_team,
                away_team=away_team,
                summary_url=urljoin(
                    BASE_URL,
                    match_href,
                ),
                source_match_id=source_match_id,
            )
        )

        seen_match_ids.add(
            source_match_id
        )

    return references


def _extract_side_player(
    cell: Tag | None,
) -> tuple[
    str,
    str | None,
] | None:
    if cell is None:
        return None

    player_name = _normalise_player_name(
        cell.get_text(
            " ",
            strip=True,
        )
    )

    if not player_name:
        return None

    anchor = cell.find(
        "a"
    )

    source_player_id = (
        _source_player_id_from_href(
            str(
                anchor.get(
                    "href",
                    "",
                )
            )
        )
        if anchor is not None
        else None
    )

    return (
        player_name,
        source_player_id,
    )


def _extract_teamsheet_row(
    row: Tag,
) -> tuple[
    str,
    tuple[str, str | None] | None,
    tuple[str, str | None] | None,
] | None:
    """
    Return:
        position,
        home player (optional),
        away player (optional)

    Home and away are intentionally independent because RLP sometimes records
    17 players for one side and only 16 for the other.
    """
    heading_cells = row.find_all(
        "th"
    )

    if not heading_cells:
        return None

    position = _normalise_text(
        heading_cells[0].get_text(
            " ",
            strip=True,
        )
    )

    if position.upper() == "HC":
        return None

    home_cells = row.find_all(
        class_="name left"
    )

    all_name_cells = row.find_all(
        class_="name"
    )

    home_cell = (
        home_cells[0]
        if home_cells
        else None
    )

    away_cell = (
        all_name_cells[1]
        if len(all_name_cells) >= 2
        else None
    )

    home_player = _extract_side_player(
        home_cell
    )

    away_player = _extract_side_player(
        away_cell
    )

    if (
        home_player is None
        and away_player is None
    ):
        return None

    return (
        position,
        home_player,
        away_player,
    )


def scrape_match_teamsheet(
    summary_url: str,
    timeout: int = 30,
) -> list[dict[str, object]]:
    """
    Scrape actual matchday player appearances from one match.

    The program table contains try scorers and goal kickers before the real
    teamsheet. The teamsheet starts at FB. From there, home and away players
    are collected independently until the coach row / end of player rows.

    This supports genuine source cases such as 17 home players vs 16 away
    players.
    """
    try:
        response = get_page(
            url=summary_url,
            timeout=timeout,
        )

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not download match page: "
            f"{summary_url}"
        ) from exc

    soup = BeautifulSoup(
        response.content,
        "html.parser",
    )

    content = soup.find(
        id="content"
    )

    if content is None:
        raise RuntimeError(
            f"Could not find match content: "
            f"{summary_url}"
        )

    program = content.find(
        class_="program"
    )

    if program is None:
        raise RuntimeError(
            f"Could not find match program: "
            f"{summary_url}"
        )

    home_records: list[
        dict[str, object]
    ] = []

    away_records: list[
        dict[str, object]
    ] = []

    teams_started = False
    lineup_order = 0

    for row in program.find_all(
        "tr"
    ):
        heading_cells = row.find_all(
            "th"
        )

        if heading_cells:
            raw_position = _normalise_text(
                heading_cells[0].get_text(
                    " ",
                    strip=True,
                )
            )

            if (
                teams_started
                and raw_position.upper() == "HC"
            ):
                break

        parsed = _extract_teamsheet_row(
            row
        )

        if parsed is None:
            continue

        (
            position,
            home_player,
            away_player,
        ) = parsed

        if not teams_started:
            if position != "FB":
                continue

            teams_started = True

        lineup_order += 1

        if home_player is not None:
            (
                home_name,
                home_source_player_id,
            ) = home_player

            home_records.append(
                {
                    "side": "home",
                    "player_name": home_name,
                    "source_player_id": home_source_player_id,
                    "position": position or None,
                    "lineup_order": lineup_order,
                    "is_starting": lineup_order <= 13,
                }
            )

        if away_player is not None:
            (
                away_name,
                away_source_player_id,
            ) = away_player

            away_records.append(
                {
                    "side": "away",
                    "player_name": away_name,
                    "source_player_id": away_source_player_id,
                    "position": position or None,
                    "lineup_order": lineup_order,
                    "is_starting": lineup_order <= 13,
                }
            )

    if not teams_started:
        raise RuntimeError(
            f"Could not find FB teamsheet start: "
            f"{summary_url}"
        )

    if len(home_records) < 13:
        raise RuntimeError(
            "Home teamsheet has fewer than 13 players "
            f"({len(home_records)}): {summary_url}"
        )

    if len(away_records) < 13:
        raise RuntimeError(
            "Away teamsheet has fewer than 13 players "
            f"({len(away_records)}): {summary_url}"
        )

    if len(home_records) > 17:
        LOGGER.warning(
            "Home teamsheet has %s players; "
            "keeping first 17: %s",
            len(home_records),
            summary_url,
        )
        home_records = home_records[:17]

    if len(away_records) > 17:
        LOGGER.warning(
            "Away teamsheet has %s players; "
            "keeping first 17: %s",
            len(away_records),
            summary_url,
        )
        away_records = away_records[:17]

    LOGGER.debug(
        "Teamsheet %s: home=%s away=%s",
        summary_url,
        len(home_records),
        len(away_records),
    )

    return (
        home_records
        + away_records
    )
