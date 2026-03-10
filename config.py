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

# ── Local TTS (Apple Silicon / CPU) ──────────────────────────────────────────
# Used when running with --local-tts kokoro|piper instead of the OpenAI API.

# --- Kokoro-82M ---
# Voice options (American):  af_heart af_bella af_nicole af_sarah af_sky
#                             am_adam  am_michael
# Voice options (British):   bf_emma  bf_isabella  bm_george  bm_lewis
LOCAL_TTS_KOKORO_VOICE = "af_heart"

# Speaking speed multiplier. 1.0 = normal, 0.9 = slightly slower (good for
# audiobooks), 1.1 = slightly faster.
LOCAL_TTS_KOKORO_SPEED = 0.95

# --- Piper TTS ---
# Voice name must match a key in _PIPER_VOICE_URLS inside local_tts.py.
# Options: en_US-amy-medium  en_US-lessac-high  en_GB-alan-medium  en_US-ryan-high
LOCAL_TTS_PIPER_VOICE = "en_US-lessac-high"

# Directory where Piper ONNX model files are cached after first download.
LOCAL_TTS_PIPER_MODEL_DIR = os.path.join(OUTPUT_DIR, "piper_models")

# Max characters per synthesis call for local backends.
# Local models have no API limit, so we use larger chunks for fewer model
# invocations while still staying memory-efficient.
LOCAL_TTS_CHUNK_SIZE = 10_000
