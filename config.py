"""
Configuration for the Wandering Inn scraper and audiobook generator.
"""

import os

# ── Scraping ──────────────────────────────────────────────────────────────────
TOC_URL = "https://wanderinginn.com/table-of-contents/"

# Delay range (seconds) between chapter requests — be a respectful scraper.
SCRAPE_DELAY_MIN = 3.0
SCRAPE_DELAY_MAX = 7.0

# HTTP headers so the server sees a real browser visit.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# ── Output paths ──────────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
BOOKS_DIR = os.path.join(OUTPUT_DIR, "books")
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")

# ── Audiobook (OpenAI TTS) ────────────────────────────────────────────────────
# Set OPENAI_API_KEY in your environment before running.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# TTS model — "tts-1" is fast; "tts-1-hd" is higher quality.
TTS_MODEL = "tts-1-hd"

# Voice options: alloy, echo, fable, onyx, nova, shimmer
TTS_VOICE = "nova"

# OpenAI TTS max chars per request (~4096 tokens ≈ ~16 000 chars is safe).
TTS_CHUNK_SIZE = 4000

# Output audio format
AUDIO_FORMAT = "mp3"
