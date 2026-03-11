"""
audiobook.py — Generate M4B audiobook files with embedded chapter markers.

Two TTS engines are supported:

OpenAI (cloud, default)
-----------------------
  - High quality, any machine, requires an API key and internet.
  - Charged per character (~$7.50–$15 per million chars).
  - Max 4 000 chars per API call; we split and stitch automatically.

Local (free, offline)
---------------------
  - No API key, no cost, works completely offline.
  - Two backends:
      kokoro  Recommended for Apple M-series. Uses Metal GPU (MPS).
              Excellent quality, ~82M params, 24 kHz output.
      piper   Lightweight CPU-only fallback. Very fast even without a GPU.
              Slightly lower quality; 22 050 Hz output.
  - Chunk size is much larger (10 000 chars) since there is no API limit.

Resuming
--------
If the final M4B for a volume already exists it is skipped, so an interrupted
run can be continued safely.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Generator, List, Tuple

from openai import OpenAI
from pydub import AudioSegment
from tqdm import tqdm

import config

log = logging.getLogger(__name__)


# ── Text splitting ─────────────────────────────────────────────────────────────

def _split_into_chunks(text: str, max_chars: int = config.TTS_CHUNK_SIZE) -> Generator[str, None, None]:
    """
    Yield text chunks of at most *max_chars* characters, splitting only on
    sentence / paragraph boundaries so audio stitching sounds natural.
    """
    sentences = re.split(r"(?<=[.!?\"'])\s+|\n\n+", text)

    buffer: List[str] = []
    buf_len = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

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


# ── Paragraph splitting with pause hints ──────────────────────────────────────

# Matches scene-break lines: * * *, ---, ───, ===, ~~~, etc.
_SCENE_BREAK_RE = re.compile(r'^[\s*\-─=~]{3,}$')


def _iter_paragraphs(content: str):
    """
    Yield (text, pause_after_ms) tuples for natural-sounding TTS output.

    - Scene-break lines (``* * *``, ``───``, ``---``) yield ``("", SCENE_BREAK_MS)``
      — silence only, nothing synthesised.
    - Every other paragraph yields ``(text, PARAGRAPH_PAUSE_MS)``.

    Synthesising paragraph-by-paragraph (rather than large chunks) lets the
    TTS engine produce better sentence-level prosody, and the inserted silences
    give the listener natural breathing room.
    """
    for block in re.split(r'\n\n+', content):
        block = block.strip()
        if not block:
            continue
        if _SCENE_BREAK_RE.match(block):
            yield "", config.AUDIO_SCENE_BREAK_MS
        else:
            yield block, config.AUDIO_PARAGRAPH_PAUSE_MS


# ── Chapter file helpers ───────────────────────────────────────────────────────

def _parse_chapter_file(path: Path) -> Tuple[str, str]:
    """
    Parse a per-chapter .txt file and return (title, content).

    Header format:
        # <title>
        <blank>
        Source: <url>
        <blank>
        <prose content begins here>
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

    title: str = path.stem
    content_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# ") and title == path.stem:
            title = stripped[2:].strip()
            content_start = i + 1
        elif stripped.startswith("Source:") or stripped == "":
            content_start = i + 1
        else:
            break

    content = "".join(lines[content_start:]).strip()
    return title, content


def _get_chapter_files(text_path: Path) -> List[Path]:
    """
    Given a merged volume .txt path, return sorted per-chapter .txt files from
    the sibling directory with the same stem. Falls back to [text_path] if no
    chapter directory exists.
    """
    chapter_dir = text_path.parent / text_path.stem
    if chapter_dir.is_dir():
        files = sorted(chapter_dir.glob("*.txt"))
        if files:
            return files
    return [text_path]


def _clean_volume_title(stem: str) -> str:
    """
    Turn a raw volume file stem into a human-readable title.

    '03_Volume 3_ Flowers of Esthelm'  →  'Volume 3: Flowers of Esthelm'
    """
    s = re.sub(r"^[\d_]+", "", stem).strip("_ ")
    s = re.sub(r"_+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"((?:Volume|Book) \d+)\s+", r"\1: ", s, count=1)
    return s


# ── M4B assembly ───────────────────────────────────────────────────────────────

def _assemble_m4b(
    chapter_mp3s: List[Path],
    chapter_titles: List[str],
    volume_title: str,
    out_path: Path,
    tmp: Path,
) -> None:
    """
    Assemble per-chapter MP3s into a single M4B with embedded chapter markers.
    """
    # Measure chapter durations in milliseconds
    durations_ms: List[int] = []
    for mp3 in chapter_mp3s:
        durations_ms.append(len(AudioSegment.from_mp3(str(mp3))))

    # Write ffmpeg concat list
    concat_path = tmp / "concat_list.txt"
    concat_path.write_text(
        "".join(f"file '{mp3.as_posix()}'\n" for mp3 in chapter_mp3s),
        encoding="utf-8",
    )

    # Write ffmetadata with chapter markers
    meta_lines = [
        ";FFMETADATA1\n",
        f"title={volume_title}\n",
        f"artist={config.AUDIO_AUTHOR}\n",
        f"album={volume_title}\n\n",
    ]
    cursor_ms = 0
    for title, dur_ms in zip(chapter_titles, durations_ms):
        safe_title = title.replace("=", r"\=").replace(";", r"\;")
        meta_lines += [
            "[CHAPTER]\n",
            "TIMEBASE=1/1000\n",
            f"START={cursor_ms}\n",
            f"END={cursor_ms + dur_ms}\n",
            f"title={safe_title}\n\n",
        ]
        cursor_ms += dur_ms

    meta_path = tmp / "ffmeta.txt"
    meta_path.write_text("".join(meta_lines), encoding="utf-8")

    # Run ffmpeg
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-i", str(meta_path),
        "-map_metadata", "1",
        "-c:a", "aac",
        "-b:a", "64k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (exit {result.returncode}):\n"
            + result.stderr.decode(errors="replace")
        )


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
                response_format="mp3",
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
    Convert a single volume text file into an M4B audiobook using OpenAI TTS.
    Each per-chapter .txt file becomes one embedded chapter.
    """
    stem = text_path.stem
    out_path = audio_dir / f"{stem}.m4b"

    if out_path.exists() and out_path.stat().st_size > 0:
        log.info("Skipping '%s' — audiobook already exists.", stem)
        return out_path

    chapter_files = _get_chapter_files(text_path)
    volume_title = _clean_volume_title(stem)
    log.info("'%s': %d chapter(s) → %s", stem, len(chapter_files), out_path.name)

    with tempfile.TemporaryDirectory(prefix="booker_tts_") as tmpdir:
        tmp = Path(tmpdir)
        chapter_mp3s: List[Path] = []
        chapter_titles: List[str] = []

        for ch_idx, ch_path in enumerate(chapter_files):
            title, content = _parse_chapter_file(ch_path)
            chapter_titles.append(title)
            chapter_seg = AudioSegment.empty()

            if config.AUDIO_CHAPTER_TITLE_CARD:
                title_bytes = _tts_chunk(client, f"Chapter: {title}")
                tc_path = tmp / f"ch{ch_idx:04d}_tc.mp3"
                tc_path.write_bytes(title_bytes)
                chapter_seg += AudioSegment.from_mp3(str(tc_path))
                chapter_seg += AudioSegment.silent(duration=config.AUDIO_CHAPTER_SILENCE_MS)
                time.sleep(0.3)

            if content:
                paragraphs = list(_iter_paragraphs(content))
                texts = [t for t, _ in paragraphs if t]
                for i, (para_text, pause_ms) in enumerate(
                    tqdm(paragraphs, desc=f"ch{ch_idx+1}", unit="para")
                ):
                    if para_text:
                        audio_bytes = _tts_chunk(client, para_text)
                        chunk_path = tmp / f"ch{ch_idx:04d}_para_{i:06d}.mp3"
                        chunk_path.write_bytes(audio_bytes)
                        chapter_seg += AudioSegment.from_mp3(str(chunk_path))
                        time.sleep(0.3)
                    chapter_seg += AudioSegment.silent(duration=pause_ms)

            ch_mp3 = tmp / f"chapter_{ch_idx:04d}.mp3"
            chapter_seg.export(str(ch_mp3), format="mp3", bitrate="128k")
            chapter_mp3s.append(ch_mp3)

        log.info("Assembling M4B with %d chapter(s)…", len(chapter_mp3s))
        _assemble_m4b(chapter_mp3s, chapter_titles, volume_title, out_path, tmp)

    log.info("Audiobook saved → %s (%.1f MB)", out_path.name, out_path.stat().st_size / 1e6)
    return out_path


# ── Local TTS audiobook generation ────────────────────────────────────────────

def generate_audiobook_local(
    text_path: Path,
    audio_dir: Path,
    backend,  # LocalTTSBackend
    mv_registry=None,   # speaker_analysis.CharacterRegistry | None
    mv_voice_map=None,  # speaker_analysis.VoiceMap | None
) -> Path:
    """
    Convert a single volume text file into an M4B audiobook using a local
    TTS backend (Kokoro or Piper). Each per-chapter .txt file becomes one
    embedded chapter. Audio is written chunk-by-chunk to avoid the 4 GB WAV
    size limit.
    """
    from local_tts import write_wav

    stem = text_path.stem
    out_path = audio_dir / f"{stem}.m4b"

    if out_path.exists() and out_path.stat().st_size > 0:
        log.info("Skipping '%s' — audiobook already exists.", stem)
        return out_path

    chapter_files = _get_chapter_files(text_path)
    volume_title = _clean_volume_title(stem)
    log.info(
        "'%s': %d chapter(s) (local TTS) → %s",
        stem, len(chapter_files), out_path.name,
    )

    with tempfile.TemporaryDirectory(prefix="booker_local_tts_") as tmpdir:
        tmp = Path(tmpdir)
        chapter_mp3s: List[Path] = []
        chapter_titles: List[str] = []

        log.info("Synthesising with %s backend…", type(backend).__name__)

        for ch_idx, ch_path in enumerate(chapter_files):
            title, content = _parse_chapter_file(ch_path)
            chapter_titles.append(title)
            chapter_seg = AudioSegment.empty()

            if config.AUDIO_CHAPTER_TITLE_CARD:
                for audio_arr in backend.synthesize_iter(
                    [f"Chapter: {title}"],
                    progress_desc=f"ch{ch_idx+1} title",
                ):
                    tc_wav = tmp / f"ch{ch_idx:04d}_tc.wav"
                    write_wav(tc_wav, audio_arr, backend.sample_rate)
                    chapter_seg += AudioSegment.from_wav(str(tc_wav))
                chapter_seg += AudioSegment.silent(duration=config.AUDIO_CHAPTER_SILENCE_MS)

            if content:
                if config.MULTI_VOICE and mv_registry is not None and mv_voice_map is not None:
                    # ── Multi-voice path ─────────────────────────────────────
                    from speaker_analysis import analyse_chapter
                    from local_tts import write_wav as _write_wav
                    segments = analyse_chapter(content, mv_registry)
                    for seg_idx, seg in enumerate(
                        tqdm(segments, desc=f"ch{ch_idx+1}/{len(chapter_files)}", unit="seg")
                    ):
                        if seg.text:
                            voice = mv_voice_map.get_voice(seg.speaker, seg.gender)
                            audio_arr = backend.synthesize_segment(seg.text, voice)
                            if audio_arr.size > 0:
                                wav_path = tmp / f"ch{ch_idx:04d}_seg_{seg_idx:06d}.wav"
                                _write_wav(wav_path, audio_arr, backend.sample_rate)
                                chapter_seg += AudioSegment.from_wav(str(wav_path))
                        chapter_seg += AudioSegment.silent(duration=seg.pause_ms)
                else:
                    # ── Single-voice path ─────────────────────────────────────
                    paragraphs = list(_iter_paragraphs(content))
                    texts = [t for t, _ in paragraphs if t]
                    audio_iter = backend.synthesize_iter(
                        texts, progress_desc=f"ch{ch_idx+1}/{len(chapter_files)}"
                    )
                    audio_queue = list(audio_iter)
                    audio_idx = 0
                    for para_text, pause_ms in paragraphs:
                        if para_text:
                            if audio_idx < len(audio_queue):
                                wav_path = tmp / f"ch{ch_idx:04d}_para_{audio_idx:06d}.wav"
                                write_wav(wav_path, audio_queue[audio_idx], backend.sample_rate)
                                chapter_seg += AudioSegment.from_wav(str(wav_path))
                                audio_idx += 1
                        chapter_seg += AudioSegment.silent(duration=pause_ms)

            ch_mp3 = tmp / f"chapter_{ch_idx:04d}.mp3"
            chapter_seg.export(str(ch_mp3), format="mp3", bitrate="128k")
            chapter_mp3s.append(ch_mp3)

        log.info("Assembling M4B with %d chapter(s)…", len(chapter_mp3s))
        _assemble_m4b(chapter_mp3s, chapter_titles, volume_title, out_path, tmp)

    log.info(
        "Audiobook saved → %s (%.1f MB)", out_path.name, out_path.stat().st_size / 1e6
    )
    return out_path


# ── Batch generation ───────────────────────────────────────────────────────────

def generate_all_audiobooks(
    local_tts: str | None = None,
    target_path: Path | None = None,
) -> None:
    """
    Generate M4B audiobooks for volumes in config.BOOKS_DIR.

    If *target_path* is given, only that one volume is processed (used when
    a single EPUB was imported so we don't re-convert unrelated books).
    Otherwise every top-level .txt file in BOOKS_DIR is processed.
    """
    books_dir = Path(config.BOOKS_DIR)
    audio_dir = Path(config.AUDIO_DIR)
    audio_dir.mkdir(parents=True, exist_ok=True)

    if target_path is not None:
        volume_files = [target_path] if target_path.exists() else []
    else:
        volume_files = sorted(books_dir.glob("*.txt"))

    if not volume_files:
        log.warning("No .txt volume files found in %s. Run the scraper first.", books_dir)
        return

    pending = [
        p for p in volume_files
        if not (audio_dir / f"{p.stem}.m4b").exists()
        or (audio_dir / f"{p.stem}.m4b").stat().st_size == 0
    ]

    log.info(
        "Found %d volume file(s) to convert (%d already done).",
        len(pending), len(volume_files) - len(pending),
    )

    if not pending:
        log.info("All audiobooks are already complete.")
        return

    if local_tts:
        from local_tts import get_backend
        log.info("Using local TTS backend: %s", local_tts)
        backend = get_backend(local_tts)

        mv_registry = None
        mv_voice_map = None
        if config.MULTI_VOICE:
            from speaker_analysis import CharacterRegistry, VoiceMap
            mv_registry = CharacterRegistry()
            mv_voice_map = VoiceMap()
            log.info("Multi-voice mode enabled.")

        try:
            for vol_path in pending:
                try:
                    generate_audiobook_local(
                        vol_path, audio_dir, backend,
                        mv_registry=mv_registry,
                        mv_voice_map=mv_voice_map,
                    )
                except Exception as exc:
                    log.error("Failed to generate audiobook for '%s': %s", vol_path.stem, exc)
        finally:
            backend.close()
    else:
        client = _make_client()
        for vol_path in pending:
            try:
                generate_audiobook(vol_path, audio_dir, client)
            except Exception as exc:
                log.error("Failed to generate audiobook for '%s': %s", vol_path.stem, exc)

    log.info("All audiobooks complete.  Files are in: %s", audio_dir)
