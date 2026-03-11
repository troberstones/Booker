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

# ── Human-mode scraping ───────────────────────────────────────────────────────
# Activated with --human-mode.  Makes requests indistinguishable from a real
# reader clicking through chapters in a browser.
#
# Delay buckets: (min_seconds, max_seconds, weight_percent)
# Weights must sum to 100.  Tweak to taste — the defaults model a reader who
# moves quickly most of the time but occasionally pauses or takes a break.
HUMAN_DELAY_BUCKETS = [
    (10,   25,  50),   # quick: just finished, clicked straight away
    (45,  120,  30),   # normal: read the chapter at a comfortable pace
    (180, 480,  15),   # slow/distracted: got drawn into something else
    (900, 2700,  5),   # break: made coffee / stepped away from the screen
]

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

# Output audio format (used for OpenAI intermediate chunks; final output is M4B)
AUDIO_FORMAT = "mp3"

# Author name embedded in M4B metadata.
AUDIO_AUTHOR = "pirateaba"

# Whether to synthesise a spoken "Chapter: {title}" card at the start of each chapter.
AUDIO_CHAPTER_TITLE_CARD = True

# Milliseconds of silence inserted after the title card.
AUDIO_CHAPTER_SILENCE_MS = 800

# Milliseconds of silence inserted after each paragraph (natural breath pause).
AUDIO_PARAGRAPH_PAUSE_MS = 400

# Milliseconds of silence inserted at scene breaks (* * *, ---, ───).
AUDIO_SCENE_BREAK_MS = 1500

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

# ── Multi-voice synthesis ─────────────────────────────────────────────────────
# Enabled with --multi-voice (requires --local-tts kokoro).
# Analyses dialog attribution and uses different voices per speaker gender.

# Master switch; set to True by --multi-voice flag at runtime.
MULTI_VOICE = False

# Kokoro voice pools used for character voices (narrator uses LOCAL_TTS_KOKORO_VOICE).
FEMALE_CHARACTER_VOICES = ["af_bella", "af_nicole", "af_sarah", "af_sky"]
MALE_CHARACTER_VOICES = ["am_adam", "am_michael"]

# Extra silence (ms) inserted between a dialog line and the next segment so
# voice changes sound natural rather than abrupt.
DIALOG_PAUSE_MS = 150
