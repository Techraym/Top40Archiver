from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import re
from typing import Any, Literal

import certifi
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import TOP40_BASE_URL

ChartType = Literal["top40", "tipparade"]
TIPPARADE_BASE_URL = "https://www.top40.nl/tipparade"
TOP40_YOUTUBE_PLAYLIST = "https://www.youtube.com/playlist?list=PLC800B9699743BD19"
TOP40_CA_BUNDLE = Path(
    os.getenv("TOP40_CA_BUNDLE", "/etc/top40-archiver/top40-ca-bundle.pem")
)
TIPPARADE_FIRST_ISO = (1967, 28)
TIPPARADE_30_START_ISO = (1969, 38)


@dataclass
class ChartTrack:
    position: int
    artist: str
    title: str
    youtube_url: str | None = None
    source_track_id: str | None = None


@dataclass
class ChartEdition:
    chart_type: ChartType
    edition_key: str
    chart_date: str
    year: int
    week: int
    source_url: str
    tracks: list[ChartTrack]
    warning: str | None = None


def chart_label(chart_type: ChartType) -> str:
    return "Top 40" if chart_type == "top40" else "Tipparade"


def edition_url(chart_type: ChartType = "top40", target: date | None = None) -> str:
    base = TOP40_BASE_URL if chart_type == "top40" else TIPPARADE_BASE_URL
    if target is None:
        return base
    year, week, _ = target.isocalendar()
    return f"{base}/{year}/week-{week}"


def expected_track_count(chart_type: ChartType, chart_date: date) -> int:
    if chart_type == "top40":
        return 40
    iso = chart_date.isocalendar()
    return 20 if (iso.year, iso.week) < TIPPARADE_30_START_ISO else 30


def _minimum_historical_track_count(expected: int) -> int:
    """Ondergrens voor bruikbare historische edities met bronafwijkingen."""
    return max(10, int(expected * 0.75))


def _ca_bundle() -> str:
    try:
        if TOP40_CA_BUNDLE.is_file() and TOP40_CA_BUNDLE.stat().st_size > 0:
            return str(TOP40_CA_BUNDLE)
    except OSError:
        pass
    return certifi.where()


def _http_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/124 Safari/537.36 Top40Archiver/1.8"
            )
        }
    )
    return session


def _text(node: Any, selectors: list[str]) -> str:
    for selector in selectors:
        found = node.select_one(selector)
        if found and found.get_text(" ", strip=True):
            return found.get_text(" ", strip=True)
    return ""


def _clean_video_title(value: str) -> str:
    value = re.sub(r"^\s*\d{1,2}\s*[.):-]\s*", "", value or "")
    value = re.sub(
        r"\s*[\[(](official\s*(music\s*)?(video|audio)|lyrics?|lyric\s*video|visuali[sz]er|audio|video|4k|hd)[^\])]*[\])]\s*$",
        "",
        value,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", value).strip(" -–—|\t")


def _split_artist_title(entry: dict[str, Any]) -> tuple[str, str]:
    artist = str(entry.get("artist") or entry.get("creator") or "").strip()
    title = str(entry.get("track") or "").strip()
    if artist and title:
        return artist, _clean_video_title(title)

    raw = _clean_video_title(str(entry.get("title") or ""))
    for separator in (" - ", " – ", " — ", " | "):
        if separator in raw:
            left, right = raw.split(separator, 1)
            if left.strip() and right.strip():
                return left.strip(), _clean_video_title(right)

    uploader = str(entry.get("uploader") or entry.get("channel") or "").strip()
    if uploader and uploader.lower() not in {
        "top 40",
        "de nederlandse top 40",
        "radio 538",
        "qmusic",
        "youtube",
    }:
        return re.sub(r"\s+-\s+topic$", "", uploader, flags=re.I), raw
    raise ValueError(f"Artiest en titel niet herkenbaar in playlistitem: {raw!r}")


def _edition_from_text(text: str, fallback: date) -> tuple[int, int]:
    patterns = (
        r"week\s*(\d{1,2})\D+(20\d{2})",
        r"(20\d{2})\D+week\s*(\d{1,2})",
        r"week\s*(\d{1,2})\b",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text or "", flags=re.I)
        if not match:
            continue
        if index == 0:
            return int(match.group(2)), int(match.group(1))
        if index == 1:
            return int(match.group(1)), int(match.group(2))
        return fallback.isocalendar().year, int(match.group(1))
    iso = fallback.isocalendar()
    return iso.year, iso.week


def fetch_chart_from_youtube(target: date | None = None) -> ChartEdition:
    import yt_dlp

    if target is not None:
        raise ValueError("De actuele YouTube-playlist is niet geschikt voor historische weken")

    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playliststart": 1,
        "playlistend": 40,
        "ignoreerrors": False,
        "socket_timeout": 30,
        "retries": 3,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        data = ydl.extract_info(TOP40_YOUTUBE_PLAYLIST, download=False)

    entries = [entry for entry in (data or {}).get("entries", []) if entry]
    if len(entries) != 40:
        raise ValueError(
            f"De officiële YouTube-playlist leverde {len(entries)} items op; exact 40 vereist."
        )

    tracks: list[ChartTrack] = []
    seen_urls: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        artist, title = _split_artist_title(entry)
        video_id = str(entry.get("id") or "").strip()
        url = entry.get("webpage_url") or entry.get("url")
        if video_id and (not url or not str(url).startswith("http")):
            url = f"https://www.youtube.com/watch?v={video_id}"
        url = str(url or "").strip() or None
        if url and url in seen_urls:
            raise ValueError(f"Dubbele YouTube-URL in Top 40-playlist: {url}")
        if url:
            seen_urls.add(url)
        tracks.append(ChartTrack(position, artist, title, url, video_id or None))

    today = date.today()
    edition_text = " ".join(str((data or {}).get(key) or "") for key in ("title", "description"))
    year, week = _edition_from_text(edition_text, today)
    monday = date.fromisocalendar(year, week, 1)
    return ChartEdition(
        chart_type="top40",
        edition_key=f"{year}-W{week:02d}",
        chart_date=monday.isoformat(),
        year=year,
        week=week,
        source_url=TOP40_YOUTUBE_PLAYLIST,
        tracks=tracks,
    )


def _parse_year_week(soup: BeautifulSoup, source_url: str) -> tuple[int, int]:
    heading = soup.get_text(" ", strip=True)
    match = re.search(r"week\s+(\d{1,2})\s*,?\s*((?:19|20)\d{2})", heading, re.I)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = re.search(r"/((?:19|20)\d{2})/week-(\d{1,2})", source_url)
    if match:
        return int(match.group(1)), int(match.group(2))
    iso = date.today().isocalendar()
    return iso.year, iso.week


def _track_id_from_href(href: str) -> str | None:
    matches = re.findall(r"-(\d+)(?=[/?#]|$)", href)
    return matches[-1] if matches else None


def _detail_link_texts(node: Any) -> tuple[list[str], str | None]:
    """Read title/artist from current Top40.nl item detail links."""
    values: list[str] = []
    track_id: str | None = None

    for link in node.select("a[href]"):
        href = str(link.get("href") or "")
        link_track_id = _track_id_from_href(href)
        if link_track_id is None:
            continue

        if track_id is None:
            track_id = link_track_id

        value = link.get_text(" ", strip=True)
        if value and value not in values:
            values.append(value)

    return values, track_id


def parse_chart(
    html: str,
    source_url: str,
    chart_type: ChartType = "top40",
    allow_incomplete: bool = False,
) -> ChartEdition:
    soup = BeautifulSoup(html, "html.parser")
    year, week = _parse_year_week(soup, source_url)
    monday = date.fromisocalendar(year, week, 1)
    if chart_type == "tipparade" and (year, week) < TIPPARADE_FIRST_ISO:
        raise ValueError("Deze week ligt vóór het begin van de Tipparade")

    expected = expected_track_count(chart_type, monday)
    found: dict[int, ChartTrack] = {}
    candidates = soup.select(
        "article, li.list-item, .chart-list__item, .top40-list__item, "
        ".tipparade-list__item, [data-position], [data-rank], "
        "[class*='chart-item'], [class*='top40-item'], [class*='tipparade-item']"
    )
    for node in candidates:
        raw_position = (
            node.get("data-position")
            or node.get("data-rank")
            or _text(
                node,
                [
                    ".list-item__position",
                    ".top40-list__item__info__position",
                    ".position",
                    "[class*='position']",
                    ".number",
                    "[class*='rank']",
                ],
            )
        )
        position_match = re.search(r"\b([1-9]|[1-3]\d|40)\b", str(raw_position))
        if not position_match:
            continue
        position = int(position_match.group(1))
        if position > expected:
            continue

        title = _text(
            node,
            [
                ".list-item__title",
                ".chart-list__title",
                ".title",
                "[class*='title']",
                "h2",
                "h3",
            ],
        )
        artist = _text(
            node,
            [
                ".list-item__artist",
                ".chart-list__artist",
                ".artist",
                "[class*='artist']",
                ".name",
            ],
        )

        detail_values, detail_track_id = _detail_link_texts(node)
        if not title and detail_values:
            title = detail_values[0]
        if not artist and len(detail_values) >= 2:
            artist = detail_values[1]

        link = node.select_one("a[href]")
        href = str(link.get("href") or "") if link else ""
        source_track_id = detail_track_id
        if source_track_id is None:
            source_track_id = _track_id_from_href(href)

        if title and artist and title != artist:
            found[position] = ChartTrack(position, artist, title, None, source_track_id)

    if len(found) < max(10, expected // 2):
        for script in soup.find_all("script"):
            text = script.string or script.get_text()
            if not text or len(text) < 20:
                continue
            try:
                data = json.loads(text)
            except Exception:
                continue

            def walk(obj: Any) -> None:
                if isinstance(obj, dict):
                    position = obj.get("position") or obj.get("rank") or obj.get("currentPosition")
                    artist = obj.get("artist") or obj.get("artistName")
                    title = obj.get("title") or obj.get("trackTitle") or obj.get("name")
                    track_id = obj.get("id") or obj.get("trackId")
                    if isinstance(artist, dict):
                        artist = artist.get("name")
                    if str(position).isdigit() and artist and title:
                        pos = int(position)
                        if 1 <= pos <= expected:
                            found[pos] = ChartTrack(
                                pos,
                                str(artist),
                                str(title),
                                None,
                                str(track_id) if track_id else None,
                            )
                    for value in obj.values():
                        walk(value)
                elif isinstance(obj, list):
                    for value in obj:
                        walk(value)

            walk(data)

    tracks = [found[position] for position in range(1, expected + 1) if position in found]
    warning: str | None = None
    if len(tracks) != expected:
        message = (
            f"{chart_label(chart_type)} leverde {len(tracks)} herkenbare noteringen op; "
            f"exact {expected} verwacht voor {year}-W{week:02d}."
        )
        minimum = _minimum_historical_track_count(expected)
        if not allow_incomplete or len(tracks) < minimum:
            raise ValueError(message)
        warning = (
            f"{message} De {len(tracks)} bruikbare noteringen zijn opgeslagen en "
            "de historische verwerking gaat automatisch verder."
        )

    return ChartEdition(
        chart_type=chart_type,
        edition_key=f"{year}-W{week:02d}",
        chart_date=monday.isoformat(),
        year=year,
        week=week,
        source_url=source_url,
        tracks=tracks,
        warning=warning,
    )


def fetch_chart_from_website(
    target: date | None = None,
    chart_type: ChartType = "top40",
    allow_incomplete: bool = False,
) -> ChartEdition:
    url = edition_url(chart_type, target)
    with _http_session() as session:
        response = session.get(url, timeout=30, verify=_ca_bundle())
        response.raise_for_status()
    return parse_chart(
        response.text,
        response.url,
        chart_type,
        allow_incomplete=allow_incomplete,
    )


def fetch_chart(
    target: date | None = None,
    chart_type: ChartType = "top40",
) -> ChartEdition:
    errors: list[str] = []
    sources = []
    if chart_type == "top40" and target is None:
        sources.append(lambda: fetch_chart_from_youtube(None))
    sources.append(lambda: fetch_chart_from_website(target, chart_type))

    for source in sources:
        try:
            return source()
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError(
        f"Geen {chart_label(chart_type)}-bron kon worden gelezen. " + " | ".join(errors)
    )
