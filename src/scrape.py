"""Scrape and clean Bolius articles."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
import trafilatura
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Bolius blocks obvious bot UAs (403). A normal desktop UA works fine and
# the request volume is tiny (one request per article, run weekly).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30


@dataclass
class Article:
    """A scraped Bolius article."""

    url: str
    title: str
    text: str
    published_date: str  # ISO 8601
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Phrases that mark boilerplate sections we want to strip out
_NOISE_PATTERNS = [
    re.compile(r"(?im)^læs også[: ].*$"),
    re.compile(r"(?im)^se også[: ].*$"),
    re.compile(r"(?im)^del på facebook.*$"),
    re.compile(r"(?im)^del artiklen.*$"),
    re.compile(r"(?im)^foto[: ].*$"),
    re.compile(r"(?im)^arkivfoto[: ].*$"),
    re.compile(r"(?im)^illustration[: ].*$"),
    re.compile(r"(?im)^kilde[r]?[: ].*$"),
    re.compile(r"(?im)^tilmeld dig.*nyhedsbrev.*$"),
    re.compile(r"(?im)^følg os på.*$"),
    re.compile(r"(?im)^cookies?.*samtykke.*$"),
]


def _clean_text(text: str) -> str:
    """Strip boilerplate, collapse whitespace, normalise dashes."""
    for pattern in _NOISE_PATTERNS:
        text = pattern.sub("", text)
    # Collapse runs of blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Trim trailing/leading whitespace per line
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text.strip()


def _format_date_dk(iso_date: str) -> str:
    """Render an ISO date as a Danish-friendly spoken date."""
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    except ValueError:
        return iso_date
    months = [
        "januar", "februar", "marts", "april", "maj", "juni",
        "juli", "august", "september", "oktober", "november", "december",
    ]
    return f"{dt.day}. {months[dt.month - 1]} {dt.year}"


def _short_topic(title: str) -> str:
    """Pick a short topic phrase from the title for the outro."""
    first = re.split(r"[—:\-–|]", title, maxsplit=1)[0].strip()
    if len(first) > 60:
        first = first[:60].rsplit(" ", 1)[0]
    return first or title


def _build_intro(title: str, published_date: str) -> str:
    return f"Fra Bolius. {title}. Publiceret {_format_date_dk(published_date)}."


def _build_outro(title: str) -> str:
    topic = _short_topic(title)
    return f"Det var artiklen om {topic}. Næste afsnit følger."


def fetch_html(url: str) -> str | None:
    """GET a URL and return its HTML, or None on failure."""
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "da,en;q=0.7",
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("Network error fetching %s: %s", url, exc)
        return None
    if resp.status_code != 200:
        logger.warning("HTTP %s for %s", resp.status_code, url)
        return None
    return resp.text


def scrape_article(url: str, html: str | None = None) -> Article | None:
    """Scrape a Bolius article URL and return an Article, or None on failure."""
    if html is None:
        html = fetch_html(url)
    if not html:
        return None

    # Extract main text with trafilatura — best at removing boilerplate
    extracted = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not extracted:
        logger.warning("trafilatura returned no text for %s", url)
        return None

    # Pull metadata (title, date) — fall back to BeautifulSoup if needed
    metadata = trafilatura.extract_metadata(html)
    title = (metadata.title if metadata and metadata.title else "").strip()
    published = (metadata.date if metadata and metadata.date else "").strip()

    if not title:
        soup = BeautifulSoup(html, "lxml")
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = og["content"].strip()
        elif soup.title and soup.title.string:
            title = soup.title.string.strip()
    if not title:
        title = url.rsplit("/", 1)[-1].replace("-", " ")

    if not published:
        published = datetime.now(timezone.utc).date().isoformat()
    elif len(published) == 10:  # YYYY-MM-DD
        pass

    # Normalise to full ISO 8601 with time at noon UTC for stable RSS sorting
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(hour=12, tzinfo=timezone.utc)
        published_iso = dt.isoformat()
    except ValueError:
        published_iso = datetime.now(timezone.utc).isoformat()

    body = _clean_text(extracted)
    intro = _build_intro(title, published_iso)
    outro = _build_outro(title)
    full_text = f"{intro}\n\n{body}\n\n{outro}"

    description = body[:200].rsplit(" ", 1)[0] + "…" if len(body) > 200 else body

    return Article(
        url=url,
        title=title,
        text=full_text,
        published_date=published_iso,
        description=description,
    )


def find_articles_by_topic(topic: str, limit: int = 10) -> list[str]:
    """Search Bolius for a topic and return candidate article URLs.

    Used as a recovery aid when URLs in articles.txt 404. Returns up to
    `limit` URLs that look like article pages (i.e. not category pages).
    """
    search_url = f"https://www.bolius.dk/sog?q={quote_plus(topic)}"
    html = fetch_html(search_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    seen: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin("https://www.bolius.dk/", a["href"])
        # Article URLs on Bolius typically end with a numeric id
        if not href.startswith("https://www.bolius.dk/"):
            continue
        if "/sog" in href or "/tag/" in href or "/emne/" in href:
            continue
        if not re.search(r"-\d{3,}$", href):
            continue
        if href in seen:
            continue
        seen.append(href)
        if len(seen) >= limit:
            break
    return seen
