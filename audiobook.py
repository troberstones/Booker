"""
audiobook.py — Generate MP3 audiobook files from cleaned book text.

Strategy
--------
The Wandering Inn is enormous (millions of words).  The OpenAI TTS API accepts
at most ~4 096 tokens (~4 000 characters) per request.  We therefore:

  1. Split the book text into sentence-aware chunks of ≤ TTS_CHUNK_SIZE chars.
  2. Send each chunk to the API and save the returned audio as a temp MP3.
  3. Concatenate all the temp MP3s into one final file using pydub.
  4. Clean up the temp files.

One MP3 is produced per *volume* text file found in config.BOOKS_DIR.

Resuming
--------
If the final MP3 for a volume already exists it is skipped, so an interrupted
run can be continued safely.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Generator, List

from openai import OpenAI
from pydub import AudioSegment
from tqdm import tqdm

import config

log = logging.getLogger(__name__)


# ── Text splitting ─────────────────────────────────────────────────────────────

# We split on sentence boundaries so the TTS engine never receives a
# mid-sentence cut, which would produce an awkward pause in the recording.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _split_into_chunks(text: str, max_chars: int = config.TTS_CHUNK_SIZE) -> Generator[str, None, None]:
    """
    Yield text chunks of at most *max_chars* characters, splitting only on
    sentence / paragraph boundaries so audio stitching sounds natural.
    """
    # Split on sentence-ending punctuation or double newlines (paragraph break).
    sentences = re.split(r"(?<=[.!?\"'])\s+|\n\n+", text)

    buffer: List[str] = []
    buf_len = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # If a single sentence is too long, break it at the max without worrying
        # about sentence integrity (rare, but possible with very long dialogue).
        while len(sentence) > max_chars:
            yield sentence[:max_chars]
            sentence = sentence[max_chars:]

        if buf_len + len(sentence) + 1 > max_chars:
            if buffer:
                yield " ".join(buffer)
            buffer = [sentence]
            buf_len = len(sentence)
        else:
            buffer.append(sentence)
            buf_len += len(sentence) + 1

    if buffer:
        yield " ".join(buffer)


# ── OpenAI TTS ─────────────────────────────────────────────────────────────────

def _make_client() -> OpenAI:
    if not config.OPENAI_API_KEY:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set.  "
            "Export it in your shell before running:\n"
            "  export OPENAI_API_KEY='sk-...'"
        )
    return OpenAI(api_key=config.OPENAI_API_KEY)


def _tts_chunk(client: OpenAI, text: str, retries: int = 4) -> bytes:
    """Send one text chunk to OpenAI TTS and return the raw MP3 bytes."""
    delay = 2
    for attempt in range(retries):
        try:
            response = client.audio.speech.create(
                model=config.TTS_MODEL,
                voice=config.TTS_VOICE,
                input=text,
                response_format=config.AUDIO_FORMAT,
            )
            return response.content
        except Exception as exc:
            if attempt == retries - 1:
                raise
            log.warning("TTS request failed (%s); retrying in %ds…", exc, delay)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


# ── Per-volume audiobook generation ───────────────────────────────────────────

def generate_audiobook(text_path: Path, audio_dir: Path, client: OpenAI) -> Path:
    """
    Convert a single volume text file into an MP3 audiobook.

    Returns the path to the generated MP3.
    """
    stem = text_path.stem
    out_path = audio_dir / f"{stem}.mp3"

    if out_path.exists() and out_path.stat().st_size > 0:
        log.info("Skipping '%s' — audiobook already exists.", stem)
        return out_path

    text = text_path.read_text(encoding="utf-8").strip()
    if not text:
        log.warning("'%s' is empty — nothing to convert.", stem)
        return out_path

    chunks = list(_split_into_chunks(text))
    log.info("'%s': %d chunks → %s", stem, len(chunks), out_path.name)

    temp_files: List[Path] = []

    with tempfile.TemporaryDirectory(prefix="booker_tts_") as tmpdir:
        tmp = Path(tmpdir)

        for i, chunk in enumerate(tqdm(chunks, desc=stem, unit="chunk")):
            chunk_path = tmp / f"chunk_{i:06d}.mp3"
            audio_bytes = _tts_chunk(client, chunk)
            chunk_path.write_bytes(audio_bytes)
            temp_files.append(chunk_path)

            # Brief pause between API calls to stay within rate limits.
            if i < len(chunks) - 1:
                time.sleep(0.3)

        log.info("Concatenating %d audio chunks…", len(temp_files))
        combined = AudioSegment.empty()
        for chunk_path in temp_files:
            combined += AudioSegment.from_mp3(chunk_path)

        combined.export(str(out_path), format="mp3", bitrate="128k")

    log.info("Audiobook saved → %s (%.1f MB)", out_path.name, out_path.stat().st_size / 1e6)
    return out_path


# ── Batch generation ───────────────────────────────────────────────────────────

def generate_all_audiobooks() -> None:
    """
    Find every top-level .txt volume file in config.BOOKS_DIR and generate
    an MP3 audiobook for each one.
    """
    books_dir = Path(config.BOOKS_DIR)
    audio_dir = Path(config.AUDIO_DIR)
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Top-level .txt files are the merged per-volume files created by scraper.py.
    volume_files = sorted(books_dir.glob("*.txt"))

    if not volume_files:
        log.warning(
            "No .txt volume files found in %s.  "
            "Run the scraper first.",
            books_dir,
        )
        return

    log.info("Found %d volume file(s) to convert.", len(volume_files))
    client = _make_client()

    for vol_path in volume_files:
        try:
            generate_audiobook(vol_path, audio_dir, client)
        except Exception as exc:
            log.error("Failed to generate audiobook for '%s': %s", vol_path.stem, exc)

    log.info("All audiobooks complete.  Files are in: %s", audio_dir)
