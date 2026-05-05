"""Tests for src.scrape using a mocked HTML fixture."""
from __future__ import annotations

from pathlib import Path

import pytest

from src import scrape

FIXTURE = Path(__file__).parent / "fixtures" / "sample_article.html"


@pytest.fixture
def sample_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_scrape_article_extracts_title_and_text(sample_html: str) -> None:
    article = scrape.scrape_article(
        "https://www.bolius.dk/skimmelsvamp-test-12345", html=sample_html
    )
    assert article is not None
    assert "Skimmelsvamp" in article.title
    assert "Skimmelsvamp opstår" in article.text
    assert article.url.endswith("12345")


def test_scrape_article_strips_boilerplate(sample_html: str) -> None:
    article = scrape.scrape_article(
        "https://www.bolius.dk/skimmelsvamp-test-12345", html=sample_html
    )
    assert article is not None
    text_lower = article.text.lower()
    # Boilerplate phrases must be gone
    assert "læs også" not in text_lower
    assert "del på facebook" not in text_lower
    assert "tilmeld dig" not in text_lower
    assert "følg os på" not in text_lower
    assert "foto:" not in text_lower


def test_scrape_article_includes_intro_and_outro(sample_html: str) -> None:
    article = scrape.scrape_article(
        "https://www.bolius.dk/skimmelsvamp-test-12345", html=sample_html
    )
    assert article is not None
    assert article.text.startswith("Fra Bolius.")
    assert "Næste afsnit følger" in article.text


def test_scrape_article_has_iso_date(sample_html: str) -> None:
    article = scrape.scrape_article(
        "https://www.bolius.dk/skimmelsvamp-test-12345", html=sample_html
    )
    assert article is not None
    # ISO 8601 starts with YYYY-MM-DD
    assert article.published_date[:4].isdigit()
    assert article.published_date[4] == "-"


def test_description_is_short(sample_html: str) -> None:
    article = scrape.scrape_article(
        "https://www.bolius.dk/skimmelsvamp-test-12345", html=sample_html
    )
    assert article is not None
    assert len(article.description) <= 210  # 200 chars + ellipsis word


def test_scrape_returns_none_on_empty_html() -> None:
    assert scrape.scrape_article("https://example.com/x", html="") is None


def test_clean_text_removes_noise() -> None:
    raw = "Tekst.\nLæs også: andet.\nDel på Facebook\nFoto: noget.\nMere tekst."
    cleaned = scrape._clean_text(raw)
    assert "Læs også" not in cleaned
    assert "Del på Facebook" not in cleaned
    assert "Foto:" not in cleaned
    assert "Mere tekst." in cleaned
