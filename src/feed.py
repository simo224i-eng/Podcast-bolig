"""Generate a podcast RSS 2.0 feed with iTunes tags."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from feedgen.feed import FeedGenerator

logger = logging.getLogger(__name__)

PODCAST_TITLE = "Bolius for jurister — byggeteknik til ejerskifte"
PODCAST_DESCRIPTION = (
    "Automatisk genererede oplæsninger af Bolius-artikler om byggeteknik, "
    "fokuseret på emner relevante for ejerskifteforsikringer."
)
PODCAST_LANGUAGE = "da"
PODCAST_AUTHOR = "Bolius (oplæst automatisk)"
PODCAST_CATEGORY = "Education"


def _parse_date(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def build_feed(
    episodes: Iterable[dict],
    feed_url: str,
    site_url: str,
    output_path: Path,
) -> Path:
    """Build feed.xml from a list of episode dicts.

    Each episode dict must contain: url, title, description, published_date,
    mp3_filename, mp3_size_bytes, audio_base_url.
    """
    fg = FeedGenerator()
    fg.load_extension("podcast")

    fg.title(PODCAST_TITLE)
    fg.description(PODCAST_DESCRIPTION)
    fg.link(href=site_url, rel="alternate")
    fg.link(href=feed_url, rel="self")
    fg.language(PODCAST_LANGUAGE)
    fg.author({"name": PODCAST_AUTHOR})
    fg.generator("bolius-podcast")

    fg.podcast.itunes_author(PODCAST_AUTHOR)
    fg.podcast.itunes_summary(PODCAST_DESCRIPTION)
    fg.podcast.itunes_category(PODCAST_CATEGORY)
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_owner(name="Bolius Podcast", email="noreply@example.com")

    # Newest first — feedgen reverses by default but we sort explicitly
    episodes_sorted = sorted(
        episodes,
        key=lambda e: _parse_date(e["published_date"]),
        reverse=True,
    )

    for ep in episodes_sorted:
        fe = fg.add_entry()
        fe.id(ep["url"])
        fe.title(ep["title"])
        fe.description(ep["description"])
        fe.link(href=ep["url"])
        fe.published(_parse_date(ep["published_date"]))
        audio_url = f"{ep['audio_base_url'].rstrip('/')}/{ep['mp3_filename']}"
        fe.enclosure(audio_url, str(ep["mp3_size_bytes"]), "audio/mpeg")
        fe.podcast.itunes_summary(ep["description"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fg.rss_file(str(output_path), pretty=True)
    logger.info("Wrote feed with %d episodes to %s", len(list(episodes_sorted)), output_path)
    return output_path
