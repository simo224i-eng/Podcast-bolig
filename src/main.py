"""Orchestrator: read articles.txt, scrape, synthesize, build feed."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import feed as feed_mod
from . import scrape as scrape_mod
from . import tts as tts_mod

logger = logging.getLogger("bolius_podcast")

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_FILE = ROOT / "articles.txt"
# GitHub Pages only supports / or /docs as the publishing folder, so we
# write the public artefacts (mp3 + feed.xml) into docs/.
OUTPUT_DIR = ROOT / "docs"
STATE_DIR = ROOT / "state"
STATE_FILE = STATE_DIR / "processed.json"
FEED_FILE = OUTPUT_DIR / "feed.xml"


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_articles_list(path: Path) -> list[str]:
    if not path.exists():
        logger.warning("%s does not exist — no articles to process.", path)
        return []
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"episodes": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("State file is corrupt; starting fresh.")
        return {"episodes": {}}
    data.setdefault("episodes", {})
    return data


def save_state(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _slugify(text: str, max_len: int = 60) -> str:
    text = text.lower()
    # Danish specials
    text = (
        text.replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
        .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    )
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0]
    return text or "episode"


def _mp3_filename(article: scrape_mod.Article) -> str:
    digest = hashlib.sha1(article.url.encode("utf-8")).hexdigest()[:8]
    return f"{_slugify(article.title)}-{digest}.mp3"


def _audio_base_url() -> str:
    base = os.environ.get("AUDIO_BASE_URL", "").strip()
    if base:
        return base.rstrip("/")
    # Construct from GitHub Actions context if available
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}"
    return "https://example.github.io/bolius-podcast"


def process_url(
    url: str,
    state: dict,
    voice: str,
) -> bool:
    """Scrape, synthesize and record one article. Returns True on success."""
    if url in state["episodes"]:
        logger.info("Skipping (already processed): %s", url)
        return True

    logger.info("Scraping %s", url)
    article = scrape_mod.scrape_article(url)
    if article is None:
        logger.error("Failed to scrape %s — skipping.", url)
        return False

    mp3_name = _mp3_filename(article)
    mp3_path = OUTPUT_DIR / mp3_name
    try:
        tts_mod.synthesize_sync(article.text, mp3_path, voice=voice)
    except Exception as exc:  # noqa: BLE001 — log and continue
        logger.exception("TTS failed for %s: %s", url, exc)
        if mp3_path.exists():
            mp3_path.unlink()
        return False

    size = mp3_path.stat().st_size
    if size < 1024:
        logger.error("Generated mp3 is suspiciously small (%d bytes); discarding.", size)
        mp3_path.unlink(missing_ok=True)
        return False

    state["episodes"][url] = {
        "url": article.url,
        "title": article.title,
        "description": article.description,
        "published_date": article.published_date,
        "mp3_filename": mp3_name,
        "mp3_size_bytes": size,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "voice": voice,
    }
    logger.info("Done: %s (%d KB)", mp3_name, size // 1024)
    return True


def build_and_write_feed(state: dict) -> Path:
    audio_base = _audio_base_url()
    site_url = audio_base
    feed_url = f"{audio_base}/feed.xml"
    episodes = []
    for ep in state["episodes"].values():
        episodes.append({**ep, "audio_base_url": audio_base})
    return feed_mod.build_feed(
        episodes=episodes,
        feed_url=feed_url,
        site_url=site_url,
        output_path=FEED_FILE,
    )


def cmd_run(args: argparse.Namespace) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    voice = args.voice or os.environ.get("TTS_VOICE", tts_mod.DEFAULT_VOICE)
    state = load_state(STATE_FILE)

    urls = load_articles_list(ARTICLES_FILE)
    logger.info("Loaded %d URL(s) from %s", len(urls), ARTICLES_FILE)

    failures: list[str] = []
    new_count = 0
    for url in urls:
        already = url in state["episodes"]
        ok = process_url(url, state, voice=voice)
        if not ok:
            failures.append(url)
            continue
        if not already:
            new_count += 1
            # Persist state after every successful new episode so a mid-run
            # crash doesn't lose work.
            save_state(state, STATE_FILE)

    save_state(state, STATE_FILE)
    build_and_write_feed(state)

    logger.info(
        "Run finished. New episodes: %d. Total: %d. Failures: %d.",
        new_count,
        len(state["episodes"]),
        len(failures),
    )
    if failures:
        logger.warning("Failed URLs (these will be retried next run):")
        for f in failures:
            logger.warning("  %s", f)
    # Always exit 0 — partial failures are expected (e.g. 404s for URLs
    # that have changed) and must not stop the workflow from committing
    # the episodes that *did* succeed.
    return 0


def cmd_find_topic(args: argparse.Namespace) -> int:
    urls = scrape_mod.find_articles_by_topic(args.topic, limit=args.limit)
    if not urls:
        logger.warning("No URLs found for topic %r", args.topic)
        return 1
    print(f"Top {len(urls)} candidate URLs for {args.topic!r}:")
    for u in urls:
        print(f"  {u}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bolius podcast generator")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--voice",
        help=f"edge-tts voice (default: {tts_mod.DEFAULT_VOICE}; "
        f"alt: {tts_mod.ALT_VOICE})",
    )
    parser.add_argument(
        "--find-topic",
        dest="find_topic",
        help="Search Bolius for a topic and print candidate article URLs.",
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="Max URLs from --find-topic.",
    )
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    if args.find_topic:
        args.topic = args.find_topic
        return cmd_find_topic(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
