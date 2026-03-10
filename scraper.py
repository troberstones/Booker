"""
scraper.py — Slowly and politely scrape The Wandering Inn chapters.

Flow:
  1. Fetch the Table of Contents page.
  2. Show an interactive volume-selection menu (skipped when stdin is not a TTY).
  3. For each selected volume, fetch every chapter page, extract the prose text,
     and write it to a per-chapter .txt file.
  4. Merge per-chapter files into one .txt file per volume.
  5. Honour a random delay between every request so the server isn't hammered.
"""

from __future__ import annotations

import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

import config

log = logging.getLogger(__name__)


# ── Data structures ────────────────────────────────────────────────────────────

class DownloadStatus(Enum):
    NOT_STARTED = "not started"
    PARTIAL     = "partial"
    COMPLETE    = "complete"


@dataclass
class Chapter:
    title: str
    url: str


@dataclass
class Volume:
    title: str
    chapters: List[Chapter] = field(default_factory=list)


# ── Browser profiles (human mode) ─────────────────────────────────────────────
#
# Each profile is a dict of HTTP headers that exactly matches what the named
# real browser sends on a navigation request.  Safari omits Sec-Fetch-* and
# Sec-CH-UA-* entirely; Chrome and Firefox send different subsets.

_BROWSER_PROFILES: list[dict[str, str]] = [
    # ── Chrome 124 on macOS ────────────────────────────────────────────────────
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8,"
                  "application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-CH-UA": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    },
    # ── Chrome 124 on Windows 11 ───────────────────────────────────────────────
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8,"
                  "application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-CH-UA": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    },
    # ── Firefox 125 on macOS ───────────────────────────────────────────────────
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) "
            "Gecko/20100101 Firefox/125.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                  "image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "TE": "trailers",
    },
    # ── Firefox 125 on Windows ────────────────────────────────────────────────
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
            "Gecko/20100101 Firefox/125.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                  "image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "TE": "trailers",
    },
    # ── Safari 17 on macOS ────────────────────────────────────────────────────
    # Safari deliberately omits Sec-Fetch-* and Sec-CH-UA-* headers.
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.4.1 Safari/605.1.15"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    },
]


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _make_session(human_mode: bool = False) -> requests.Session:
    session = requests.Session()
    if human_mode:
        # Pick a random profile for this session and stick with it — a real
        # user doesn't switch browsers mid-session.
        profile = random.choice(_BROWSER_PROFILES)
        session.headers.update(profile)
        log.info(
            "Human mode: using profile '%s'",
            _profile_name(profile["User-Agent"]),
        )
    else:
        session.headers.update(config.HEADERS)
    return session


def _profile_name(ua: str) -> str:
    """Return a short human-readable label for a User-Agent string."""
    if "Firefox" in ua:
        browser = "Firefox"
    elif "Safari" in ua and "Chrome" not in ua:
        browser = "Safari"
    else:
        browser = "Chrome"
    platform = "macOS" if "Macintosh" in ua or "Mac OS X" in ua else "Windows"
    return f"{browser}/{platform}"


def _get(
    session: requests.Session,
    url: str,
    retries: int = 4,
    referer: Optional[str] = None,
) -> requests.Response:
    """GET with exponential back-off on transient errors.

    If *referer* is supplied it is sent as the Referer header for this request
    only, simulating a user navigating from the previous page.
    """
    headers = {"Referer": referer} if referer else {}
    delay = 2
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=30, headers=headers)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise
            log.warning("Request failed (%s); retrying in %ds…", exc, delay)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def _polite_sleep() -> None:
    """Sleep a random amount between configured min/max to avoid hammering."""
    duration = random.uniform(config.SCRAPE_DELAY_MIN, config.SCRAPE_DELAY_MAX)
    log.debug("Sleeping %.1fs…", duration)
    time.sleep(duration)


def _human_sleep() -> None:
    """
    Sleep for a duration drawn from a weighted bucket distribution that
    mimics realistic inter-chapter pauses for a human reader.

    Buckets and weights are defined in config.HUMAN_DELAY_BUCKETS.
    """
    buckets = config.HUMAN_DELAY_BUCKETS
    weights = [b[2] for b in buckets]
    lo, hi, _ = random.choices(buckets, weights=weights, k=1)[0]
    duration = random.uniform(lo, hi)

    if duration < 60:
        label = f"{duration:.0f}s"
    elif duration < 3600:
        label = f"{duration / 60:.1f}min"
    else:
        label = f"{duration / 3600:.1f}h"

    bucket_names = ["quick", "normal", "slow", "break"]
    bucket_idx = buckets.index((lo, hi, _))
    log.info("  [human] %s pause: %s", bucket_names[bucket_idx], label)
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
    resp = _get(session, config.TOC_URL, referer="https://wanderinginn.com/")
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


# ── Volume status ──────────────────────────────────────────────────────────────

def _volume_status(volume: Volume, vol_index: int) -> tuple[DownloadStatus, int, int]:
    """
    Return (status, chapters_downloaded, total_chapters) for a volume.

    A volume is COMPLETE  if its merged .txt file exists and is non-empty.
    A volume is PARTIAL   if some per-chapter files exist but the merged file
                          is absent or empty.
    A volume is NOT_STARTED if no files have been saved yet.
    """
    total = len(volume.chapters)
    safe_title = _safe_filename(f"{vol_index:02d}_{volume.title}")
    merged_path = Path(config.BOOKS_DIR) / f"{safe_title}.txt"
    vol_dir = Path(config.BOOKS_DIR) / safe_title

    if merged_path.exists() and merged_path.stat().st_size > 0:
        return DownloadStatus.COMPLETE, total, total

    if vol_dir.exists():
        done = len(list(vol_dir.glob("*.txt")))
        if done > 0:
            return DownloadStatus.PARTIAL, done, total

    return DownloadStatus.NOT_STARTED, 0, total


# ── Interactive volume selection ───────────────────────────────────────────────

_STATUS_ICON = {
    DownloadStatus.COMPLETE:    "✓",
    DownloadStatus.PARTIAL:     "~",
    DownloadStatus.NOT_STARTED: "○",
}


def prompt_volume_selection(
    volumes: List[Volume],
    preset: Optional[str] = None,
) -> List[int]:
    """
    Ask the user which volumes to download and return a list of 0-based indices.

    Args:
        volumes: Full list of volumes parsed from the ToC.
        preset:  If given, skip the interactive prompt and interpret this string
                 directly ("all", "new", or comma/range notation like "1,3,5-7").
                 Useful for scripted / non-TTY invocations.

    Returns:
        Sorted list of 0-based volume indices to scrape.
    """
    os.makedirs(config.BOOKS_DIR, exist_ok=True)

    # Gather status for every volume up front.
    statuses = [_volume_status(v, i + 1) for i, v in enumerate(volumes)]

    # ── Non-interactive shortcut ───────────────────────────────────────────────
    if preset is not None:
        return _parse_selection(preset, volumes, statuses)

    # ── Interactive prompt ─────────────────────────────────────────────────────
    print()
    print("  Available volumes")
    print("  " + "─" * 60)

    for i, (volume, (status, done, total)) in enumerate(zip(volumes, statuses), start=1):
        icon = _STATUS_ICON[status]
        label = status.value
        if status is DownloadStatus.PARTIAL:
            label = f"partial ({done}/{total} chapters)"
        elif status is DownloadStatus.COMPLETE:
            label = f"complete ({total} chapters)"
        else:
            label = f"not started ({total} chapters)"

        print(f"  [{i:>2}]  {icon}  {volume.title:<45}  {label}")

    print()
    print("  Enter your selection:")
    print("    A number or comma-separated list   e.g.  1  or  1,3,5")
    print("    A range                            e.g.  2-4  or  1,3-5,7")
    print("    all   — download every volume")
    print("    new   — download only volumes not yet started")
    print()

    while True:
        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(0)

        if not raw:
            continue

        try:
            indices = _parse_selection(raw, volumes, statuses)
        except ValueError as exc:
            print(f"  Invalid input: {exc}  — please try again.")
            continue

        if not indices:
            print("  No volumes matched that selection — please try again.")
            continue

        # Confirm what was selected.
        print()
        print(f"  Selected {len(indices)} volume(s):")
        for idx in indices:
            print(f"    • {volumes[idx].title}")
        print()
        return indices


def _parse_selection(
    raw: str,
    volumes: List[Volume],
    statuses: list,
) -> List[int]:
    """
    Parse a selection string into a sorted list of 0-based volume indices.

    Accepted formats
    ----------------
    all         every volume
    new         volumes with NOT_STARTED status
    1           single volume (1-based)
    1,3,5       multiple volumes
    2-4         inclusive range
    1,3-5,7     mixed
    """
    raw = raw.strip().lower()

    if raw == "all":
        return list(range(len(volumes)))

    if raw == "new":
        return [i for i, (status, _, _) in enumerate(statuses)
                if status is DownloadStatus.NOT_STARTED]

    indices: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            parts = token.split("-", 1)
            try:
                lo, hi = int(parts[0]), int(parts[1])
            except ValueError:
                raise ValueError(f"'{token}' is not a valid range")
            if lo < 1 or hi > len(volumes) or lo > hi:
                raise ValueError(
                    f"range {lo}-{hi} is out of bounds (1–{len(volumes)})"
                )
            indices.extend(range(lo - 1, hi))
        else:
            try:
                n = int(token)
            except ValueError:
                raise ValueError(f"'{token}' is not a number")
            if n < 1 or n > len(volumes):
                raise ValueError(f"{n} is out of bounds (1–{len(volumes)})")
            indices.append(n - 1)

    # Deduplicate while preserving order.
    seen: set[int] = set()
    result: list[int] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            result.append(idx)
    return sorted(result)


# ── Main scrape routine ────────────────────────────────────────────────────────

def scrape_all(
    resume: bool = True,
    volumes_preset: Optional[str] = None,
    human_mode: bool = False,
) -> None:
    """
    Scrape selected volumes and write plain-text files under output/books/.

    Args:
        resume:         If True (default), already-downloaded chapter files are
                        skipped so a crashed run can be restarted safely.
        volumes_preset: Passed directly to prompt_volume_selection as the
                        *preset* argument.  If None and stdin is a TTY, the
                        interactive menu is shown.  If None and stdin is not a
                        TTY, defaults to "new" (only not-yet-started volumes).
        human_mode:     If True, rotate browser profiles, send realistic
                        Referer chains, and use human-paced delays between
                        chapter downloads.
    """
    if human_mode:
        log.info(
            "Human mode enabled — rotating browser profiles, realistic delays. "
            "This will be slow by design."
        )
    os.makedirs(config.BOOKS_DIR, exist_ok=True)
    session = _make_session(human_mode=human_mode)
    volumes = fetch_toc(session)

    # Determine which volumes to scrape.
    if volumes_preset is None and not sys.stdin.isatty():
        # Non-interactive environment (piped, cron, etc.) — default to "new".
        log.info("Non-interactive mode: defaulting to 'new' (undownloaded volumes).")
        volumes_preset = "new"

    selected_indices = prompt_volume_selection(volumes, preset=volumes_preset)

    if not selected_indices:
        log.info("No volumes selected — nothing to do.")
        return

    log.info(
        "Scraping %d volume(s): %s",
        len(selected_indices),
        ", ".join(volumes[i].title for i in selected_indices),
    )

    for vol_index, volume in (
        (i + 1, volumes[i]) for i in selected_indices
    ):
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

        # Track the previous URL so each request carries a realistic Referer.
        referer: Optional[str] = config.TOC_URL

        for ch_index, chapter in enumerate(volume.chapters, start=1):
            ch_filename = vol_dir / f"{ch_index:04d}_{_safe_filename(chapter.title)}.txt"

            if resume and ch_filename.exists() and ch_filename.stat().st_size > 0:
                log.info("  [skip] %s (already downloaded)", chapter.title)
                referer = chapter.url  # keep the chain intact even when skipping
                continue

            log.info(
                "  [%d/%d] Fetching: %s",
                ch_index,
                len(volume.chapters),
                chapter.title,
            )

            try:
                resp = _get(session, chapter.url, referer=referer)
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

            # Advance the referer to this chapter for the next request.
            referer = chapter.url

            if human_mode:
                _human_sleep()
            else:
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
