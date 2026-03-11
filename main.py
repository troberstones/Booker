"""
main.py — Orchestrate the full pipeline:

  0. EPUB    — import an EPUB file as a local volume (alternative to scraping)
  1. Scrape  — download all chapters from wanderinginn.com
  2. Filter  — replace profanity with clean alternatives
  3. Audio   — generate M4B audiobooks (OpenAI cloud or local model)

Run the full pipeline (OpenAI TTS):
    python main.py

Run with a local TTS model (no API key, no cost):
    python main.py --local-tts kokoro    # recommended for Apple M-series
    python main.py --local-tts piper     # lightweight CPU-only fallback

Import an EPUB then run filter + audio:
    python main.py --epub path/to/book.epub
    python main.py --epub path/to/book.epub --local-tts kokoro

Re-run just filter or audio on an already-imported EPUB:
    python main.py --epub path/to/book.epub --filter-only
    python main.py --epub path/to/book.epub --audio-only --local-tts kokoro

Run individual stages (scrape-based):
    python main.py --scrape-only
    python main.py --filter-only
    python main.py --audio-only --local-tts kokoro

Skip the interactive menu and scrape specific volumes:
    python main.py --volumes all          # every volume
    python main.py --volumes new          # only not-yet-started volumes
    python main.py --volumes 1,3,5        # specific volumes by number
    python main.py --volumes 2-4          # a range of volumes
    python main.py --volumes 1,3-5,7      # mixed

Additional flags:
    --no-resume     Re-download/re-generate even if output files exist
    --log-level     DEBUG | INFO | WARNING  (default: INFO)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wandering Inn → cleaned text → M4B audiobook pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    stage = parser.add_mutually_exclusive_group()
    stage.add_argument(
        "--scrape-only",
        action="store_true",
        help="Only run the web scraper stage.",
    )
    stage.add_argument(
        "--filter-only",
        action="store_true",
        help="Only run the profanity-filter stage.",
    )
    stage.add_argument(
        "--audio-only",
        action="store_true",
        help="Only run the audiobook-generation stage.",
    )

    parser.add_argument(
        "--epub",
        metavar="PATH",
        default=None,
        help=(
            "Import an EPUB file instead of scraping. "
            "Parsed as stage 0, then filter and audio run as normal. "
            "Combine with --filter-only or --audio-only to re-run only those "
            "stages on an already-imported EPUB. "
            "Cannot be combined with --scrape-only."
        ),
    )
    parser.add_argument(
        "--human-mode",
        action="store_true",
        help=(
            "Make the scraper appear as a real browser: rotates Chrome/Firefox/Safari "
            "profiles with matching headers, sends a Referer chain between pages, and "
            "uses human-paced delays (10s–45min). Slower but much harder to detect."
        ),
    )
    parser.add_argument(
        "--volumes",
        metavar="SELECTION",
        default=None,
        help=(
            "Which volumes to scrape, skipping the interactive menu. "
            "all=every volume, new=not yet started, "
            "or a number/range/list e.g. 1  1,3,5  2-4  1,3-5,7"
        ),
    )
    parser.add_argument(
        "--local-tts",
        metavar="BACKEND",
        choices=["kokoro", "piper"],
        default=None,
        help=(
            "Use a local TTS model instead of the OpenAI API (no cost, no internet). "
            "kokoro: recommended for Apple M-series (MPS GPU, 24 kHz, high quality). "
            "piper: lightweight CPU-only fallback (22 kHz, very fast)."
        ),
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not skip already-completed files (re-download / re-generate).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )

    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    _configure_logging(args.log_level)
    log = logging.getLogger("main")

    # --epub and --scrape-only are mutually exclusive
    if args.epub and args.scrape_only:
        log.error("--epub and --scrape-only are mutually exclusive.")
        sys.exit(1)

    epub_path = Path(args.epub) if args.epub else None
    if epub_path is not None and not epub_path.exists():
        log.error("EPUB file not found: %s", epub_path)
        sys.exit(1)

    resume = not args.no_resume
    local_tts = args.local_tts
    volumes_preset = args.volumes
    human_mode = args.human_mode
    run_all = not (args.scrape_only or args.filter_only or args.audio_only)

    # ── Stage 0: EPUB import ───────────────────────────────────────────────────
    # Skip if --filter-only or --audio-only: those mean re-run that stage on
    # an already-imported EPUB, so we don't re-parse the file.
    if epub_path is not None and not (args.filter_only or args.audio_only):
        log.info("━━━  Stage 0: EPUB import  ━━━")
        try:
            from epub_reader import read_epub
            merged_path = read_epub(epub_path)
            log.info("EPUB imported → %s", merged_path)
        except Exception as exc:
            log.error("EPUB import failed: %s", exc, exc_info=True)
            sys.exit(1)

    # ── Stage 1: Scrape ────────────────────────────────────────────────────────
    if (run_all or args.scrape_only) and epub_path is None:
        log.info("━━━  Stage 1: Scraping  ━━━")
        try:
            from scraper import scrape_all
            scrape_all(resume=resume, volumes_preset=volumes_preset, human_mode=human_mode)
        except Exception as exc:
            log.error("Scraping failed: %s", exc, exc_info=True)
            if args.scrape_only:
                sys.exit(1)

    # ── Stage 2: Filter ────────────────────────────────────────────────────────
    if run_all or args.filter_only:
        log.info("━━━  Stage 2: Profanity filtering  ━━━")
        try:
            from filter import clean_books_dir
            clean_books_dir()
        except Exception as exc:
            log.error("Filtering failed: %s", exc, exc_info=True)
            if args.filter_only:
                sys.exit(1)

    # ── Stage 3: Audiobook generation ─────────────────────────────────────────
    if run_all or args.audio_only:
        engine_label = f"local:{local_tts}" if local_tts else "OpenAI"
        log.info("━━━  Stage 3: Audiobook generation (%s)  ━━━", engine_label)
        try:
            from audiobook import generate_all_audiobooks
            generate_all_audiobooks(local_tts=local_tts)
        except EnvironmentError as exc:
            log.error("%s", exc)
            sys.exit(1)
        except Exception as exc:
            log.error("Audiobook generation failed: %s", exc, exc_info=True)
            if args.audio_only:
                sys.exit(1)

    log.info("Done.")


if __name__ == "__main__":
    main()
