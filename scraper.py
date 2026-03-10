"""
scraper.py — Slowly and politely scrape The Wandering Inn chapters.

Flow:
  1. Fetch the Table of Contents page.
  2. Parse it into a list of volumes, each containing (title, url) chapter pairs.
  3. For each chapter, fetch the page, extract the chapter body text, and
     accumulate it into the volume's text file.
  4. Honour a random delay between every request so the server isn't hammered.
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import requests
from bs4 import BeautifulSoup

import config

log = logging.getLogger(__name__)


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class Chapter:
    title: str
    url: str


@dataclass
class Volume:
    title: str
    chapters: List[Chapter] = field(default_factory=list)


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(config.HEADERS)
    return session


def _get(session: requests.Session, url: str, retries: int = 4) -> requests.Response:
    """GET with exponential back-off on transient errors."""
    delay = 2
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise
            log.warning("Request failed (%s); retrying in %ds…", exc, delay)
            time.sleep(delay)
            delay *= 2
    # unreachable, but satisfies type checkers
    raise RuntimeError("unreachable")


def _polite_sleep() -> None:
    """Sleep a random amount between configured min/max to avoid hammering."""
    duration = random.uniform(config.SCRAPE_DELAY_MIN, config.SCRAPE_DELAY_MAX)
    log.debug("Sleeping %.1fs…", duration)
    time.sleep(duration)


# ── Table-of-Contents parser ───────────────────────────────────────────────────

def fetch_toc(session: requests.Session) -> List[Volume]:
    """
    Parse the Wandering Inn Table of Contents page.

    The page uses a WordPress structure where volumes appear as <h2> or <strong>
    headings and chapters are <a> links inside list items or paragraphs beneath
    them.  We walk the DOM sequentially, creating a new Volume each time we hit
    a heading and appending Chapter objects for every hyperlink we encounter
    before the next heading.
    """
    log.info("Fetching table of contents from %s", config.TOC_URL)
    resp = _get(session, config.TOC_URL)
    soup = BeautifulSoup(resp.text, "lxml")

    # The ToC content lives inside the main article / entry-content div.
    content = (
        soup.find("div", class_="entry-content")
        or soup.find("article")
        or soup.find("main")
        or soup.body
    )

    volumes: List[Volume] = []
    current_volume: Volume | None = None

    # Walk every element that could be a heading or a chapter link.
    for element in content.descendants:
        tag = getattr(element, "name", None)

        # Volume headings — h2, h3, or <strong> that looks like a book title.
        if tag in ("h2", "h3"):
            title = element.get_text(strip=True)
            if title:
                current_volume = Volume(title=title)
                volumes.append(current_volume)
                log.info("Found volume: %s", title)
            continue

        # Chapter links
        if tag == "a":
            href = element.get("href", "")
            text = element.get_text(strip=True)
            if href.startswith("http") and "wanderinginn.com" in href and text:
                if current_volume is None:
                    current_volume = Volume(title="Uncategorised")
                    volumes.append(current_volume)
                current_volume.chapters.append(Chapter(title=text, url=href))

    log.info(
        "Table of contents: %d volumes, %d total chapters",
        len(volumes),
        sum(len(v.chapters) for v in volumes),
    )
    return volumes


# ── Chapter body extractor ─────────────────────────────────────────────────────

def _extract_chapter_text(html: str, chapter_title: str) -> str:
    """
    Pull the readable prose text out of a chapter page.

    Wandering Inn chapters are standard WordPress posts.  The body text lives
    inside <div class="entry-content">.  We strip navigation links, ads,
    and other non-prose elements.
    """
    soup = BeautifulSoup(html, "lxml")

    body = soup.find("div", class_="entry-content")
    if body is None:
        body = soup.find("article") or soup.find("main")

    if body is None:
        log.warning("Could not find content div for chapter '%s'", chapter_title)
        return ""

    # Remove non-prose elements.
    for tag in body.find_all(["script", "style", "nav", "figure", "img"]):
        tag.decompose()

    # Also nuke "next chapter / previous chapter" navigation paragraphs.
    for p in body.find_all("p"):
        links = p.find_all("a")
        text = p.get_text(strip=True).lower()
        if links and any(kw in text for kw in ("next chapter", "previous chapter", "table of contents")):
            p.decompose()

    paragraphs = []
    for elem in body.find_all(["p", "h1", "h2", "h3", "h4", "blockquote"]):
        text = elem.get_text(separator=" ", strip=True)
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)


# ── Main scrape routine ────────────────────────────────────────────────────────

def scrape_all(resume: bool = True) -> None:
    """
    Scrape every volume/chapter and write plain-text files under output/books/.

    If *resume* is True (the default), already-completed chapter files are
    skipped so a crashed run can be restarted without re-downloading.
    """
    os.makedirs(config.BOOKS_DIR, exist_ok=True)
    session = _make_session()
    volumes = fetch_toc(session)

    for vol_index, volume in enumerate(volumes, start=1):
        if not volume.chapters:
            log.info("Skipping empty volume: %s", volume.title)
            continue

        safe_vol_title = _safe_filename(f"{vol_index:02d}_{volume.title}")
        vol_dir = Path(config.BOOKS_DIR) / safe_vol_title
        vol_dir.mkdir(parents=True, exist_ok=True)

        log.info(
            "== Volume %d/%d: %s (%d chapters) ==",
            vol_index,
            len(volumes),
            volume.title,
            len(volume.chapters),
        )

        for ch_index, chapter in enumerate(volume.chapters, start=1):
            ch_filename = vol_dir / f"{ch_index:04d}_{_safe_filename(chapter.title)}.txt"

            if resume and ch_filename.exists() and ch_filename.stat().st_size > 0:
                log.info("  [skip] %s (already downloaded)", chapter.title)
                continue

            log.info(
                "  [%d/%d] Fetching: %s",
                ch_index,
                len(volume.chapters),
                chapter.title,
            )

            try:
                resp = _get(session, chapter.url)
                text = _extract_chapter_text(resp.text, chapter.title)
            except Exception as exc:
                log.error("  Failed to fetch '%s': %s", chapter.title, exc)
                _polite_sleep()
                continue

            if not text.strip():
                log.warning("  Empty text for '%s' — skipping save.", chapter.title)
            else:
                ch_filename.write_text(
                    f"# {chapter.title}\n\nSource: {chapter.url}\n\n{text}\n",
                    encoding="utf-8",
                )
                log.info("  Saved %d chars → %s", len(text), ch_filename.name)

            _polite_sleep()

        # Concatenate all chapters into one volume text file.
        _merge_volume(vol_dir, safe_vol_title)

    log.info("Scraping complete.")


def _merge_volume(vol_dir: Path, vol_title: str) -> None:
    """Combine all individual chapter files into a single volume text file."""
    chapter_files = sorted(vol_dir.glob("*.txt"))
    if not chapter_files:
        return

    merged_path = Path(config.BOOKS_DIR) / f"{vol_title}.txt"
    with merged_path.open("w", encoding="utf-8") as out:
        for ch_file in chapter_files:
            out.write(ch_file.read_text(encoding="utf-8"))
            out.write("\n\n" + "─" * 80 + "\n\n")

    log.info("Merged volume → %s (%d chapters)", merged_path.name, len(chapter_files))


def _safe_filename(name: str) -> str:
    """Strip characters that are invalid in file/directory names."""
    keep = set(" abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.()")
    safe = "".join(c if c in keep else "_" for c in name)
    return safe.strip().rstrip(".")[:120]
