"""
epub_reader.py — Import an EPUB file into the booker pipeline.

Walks the EPUB spine in reading order, extracts prose text from each
document item, saves per-chapter .txt files in the same format the
scraper produces, then merges them into a single volume .txt file.

Entry point:
    from epub_reader import read_epub
    merged_path = read_epub(Path("my_book.epub"))
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import warnings

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# EPUB files are XHTML; parsing them with an HTML parser is intentional and
# works correctly — suppress the spurious BeautifulSoup warning.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

import config

log = logging.getLogger(__name__)

# Minimum character count for a spine item to be treated as a real chapter.
# Items shorter than this are cover pages, TOC pages, copyright notices, etc.
_MIN_CONTENT_CHARS = 200

# Chapter titles that are publisher/distributor boilerplate, not prose.
# Matched case-insensitively against the extracted title.
_BOILERPLATE_TITLES = {
    "colophon", "imprint", "uncopyright", "copyright",
    "titlepage", "title page", "cover", "halftitlepage", "half title",
    "table of contents", "contents", "toc",
    "dedication", "epigraph",
}

# Tags whose text content we extract as paragraph-level blocks.
_PROSE_TAGS = ["p", "h1", "h2", "h3", "h4", "blockquote"]

# Tags we strip before extraction so their text doesn't bleed into the output.
_STRIP_TAGS = ["script", "style", "nav"]


# ── Filename sanitiser (identical to scraper._safe_filename) ───────────────────

def _safe_filename(name: str) -> str:
    """Strip characters that are invalid in file/directory names."""
    keep = set(" abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.()")
    safe = "".join(c if c in keep else "_" for c in name)
    return safe.strip().rstrip(".")[:120]


# ── EPUB item helpers ──────────────────────────────────────────────────────────

def _extract_title_and_content(html: bytes) -> Tuple[Optional[str], str]:
    """
    Parse one EPUB spine item's HTML and return (chapter_title, prose_text).

    Title is taken from the first h1/h2/h3 element, or None if none found.
    Prose text is the joined text of all p/h1-h4/blockquote elements after
    stripping script, style, and nav nodes.
    """
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    title: Optional[str] = None
    for heading_tag in ("h1", "h2", "h3"):
        heading = soup.find(heading_tag)
        if heading:
            candidate = heading.get_text(separator=" ", strip=True)
            if candidate:
                title = candidate
                break

    paragraphs: List[str] = []
    for elem in soup.find_all(_PROSE_TAGS):
        text = elem.get_text(separator=" ", strip=True)
        if text:
            paragraphs.append(text)

    return title, "\n\n".join(paragraphs)


def _volume_title_from_epub(book: epub.EpubBook) -> str:
    """Return the DC title metadata, or 'Unknown Volume' if absent."""
    titles = book.get_metadata("DC", "title")
    if titles:
        raw = titles[0][0].strip()
        if raw:
            return raw
    return "Unknown Volume"


# ── Merge helper (mirrors scraper._merge_volume) ───────────────────────────────

def _merge_volume(vol_dir: Path, safe_title: str) -> Path:
    """
    Combine all per-chapter .txt files into one volume .txt file using the
    same ─*80 separator as the scraper so filter/audio stages see an
    identical format.
    """
    chapter_files = sorted(vol_dir.glob("*.txt"))
    merged_path = Path(config.BOOKS_DIR) / f"{safe_title}.txt"

    with merged_path.open("w", encoding="utf-8") as out:
        for ch_file in chapter_files:
            out.write(ch_file.read_text(encoding="utf-8"))
            out.write("\n\n" + "─" * 80 + "\n\n")

    log.info("Merged %d chapter(s) → %s", len(chapter_files), merged_path.name)
    return merged_path


# ── Main entry point ───────────────────────────────────────────────────────────

def read_epub(epub_path: Path) -> Path:
    """
    Import an EPUB file into the booker pipeline.

    Walks the spine in reading order, skips items with fewer than
    _MIN_CONTENT_CHARS characters (cover pages, TOC, copyright notices),
    writes per-chapter .txt files under output/books/{safe_title}/,
    and merges them into output/books/{safe_title}.txt.

    Returns the Path to the merged volume .txt file.
    """
    log.info("Reading EPUB: %s", epub_path)
    book = epub.read_epub(str(epub_path))

    volume_title = _volume_title_from_epub(book)
    safe_title = _safe_filename(volume_title)
    log.info("Volume title: %s", volume_title)

    vol_dir = Path(config.BOOKS_DIR) / safe_title
    vol_dir.mkdir(parents=True, exist_ok=True)

    # Build spine ID set once for O(1) lookup
    spine_ids = {idref for idref, _ in book.spine}

    chapter_index = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        if item.get_id() not in spine_ids:
            continue

        title, content = _extract_title_and_content(item.get_content())

        if len(content) < _MIN_CONTENT_CHARS:
            log.debug("Skipping short item '%s' (%d chars)", item.get_name(), len(content))
            continue

        if title and title.lower().strip() in _BOILERPLATE_TITLES:
            log.debug("Skipping boilerplate item '%s'", title)
            continue

        chapter_index += 1
        ch_title = title if title else f"Chapter {chapter_index}"
        ch_filename = vol_dir / f"{chapter_index:04d}_{_safe_filename(ch_title)}.txt"

        ch_filename.write_text(f"# {ch_title}\n\n{content}\n", encoding="utf-8")
        log.debug("  [%04d] %d chars → %s", chapter_index, len(content), ch_filename.name)

    if chapter_index == 0:
        raise ValueError(
            f"No usable chapters found in '{epub_path}'. "
            f"All spine items had fewer than {_MIN_CONTENT_CHARS} characters."
        )

    log.info(
        "EPUB import complete: '%s' — %d chapter(s) saved to %s/",
        volume_title, chapter_index, vol_dir.name,
    )
    return _merge_volume(vol_dir, safe_title)
