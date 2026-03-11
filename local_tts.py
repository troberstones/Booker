"""
local_tts.py — Local TTS backends for Apple Silicon Macs (and any machine
               with enough RAM to run a small neural TTS model).

Supported backends
------------------
kokoro  Recommended for M-series Macs.
        Model:  Kokoro-82M (StyleTTS2-based, ~330 MB download on first run)
        Output: 24 000 Hz mono WAV
        GPU:    Apple MPS (Metal) used automatically when available.
        Install: pip install kokoro>=0.9.2 soundfile

piper   Lightweight CPU-only fallback; extremely fast even on modest hardware.
        Model:  ONNX voice file (~60–200 MB, auto-downloaded on first use)
        Output: 22 050 Hz mono WAV (varies by voice)
        GPU:    None (CPU-only by design)
        Install: pip install piper-tts

Both backends expose the same interface so audiobook.py can treat them
interchangeably.
"""

from __future__ import annotations

import logging
import urllib.request
import wave
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

import numpy as np

import config

log = logging.getLogger(__name__)


# ── Abstract base ──────────────────────────────────────────────────────────────

class LocalTTSBackend(ABC):
    """Common interface for all local TTS backends."""

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Sample rate of the audio produced by this backend."""

    @abstractmethod
    def synthesize(self, chunks: List[str], progress_desc: str = "") -> np.ndarray:
        """
        Synthesise a list of text chunks and return concatenated PCM audio
        as a float32 numpy array normalised to [-1, 1].

        Args:
            chunks:        List of text strings to synthesise.
            progress_desc: Label shown on the tqdm progress bar.
        """

    def synthesize_iter(self, chunks: List[str], progress_desc: str = ""):
        """
        Yield one float32 numpy audio array per chunk.  Avoids accumulating
        all audio in memory, preventing the 4 GB WAV limit on long volumes.
        """
        from tqdm import tqdm
        for chunk in tqdm(chunks, desc=progress_desc or type(self).__name__, unit="chunk"):
            if not chunk.strip():
                continue
            arr = self.synthesize([chunk])
            if arr.size > 0:
                yield arr

    def close(self) -> None:
        """Release any resources held by the backend (optional)."""


# ── Kokoro backend ─────────────────────────────────────────────────────────────

class KokoroBackend(LocalTTSBackend):
    """
    Kokoro-82M TTS — fast, high quality, Apple MPS accelerated.

    Voice choices (American English):
        af_heart  af_bella  af_nicole  af_sarah  af_sky
        am_adam   am_michael

    Voice choices (British English):
        bf_emma   bf_isabella
        bm_george bm_lewis
    """

    _SAMPLE_RATE = 24_000

    def __init__(
        self,
        voice: str = config.LOCAL_TTS_KOKORO_VOICE,
        speed: float = config.LOCAL_TTS_KOKORO_SPEED,
        lang_code: str = "a",  # 'a' = American English, 'b' = British English
    ) -> None:
        self._voice = voice
        self._speed = speed
        self._lang_code = lang_code
        self._pipeline = self._load_pipeline()

    def _load_pipeline(self):
        try:
            import torch
            from kokoro import KPipeline
        except ImportError as exc:
            raise ImportError(
                "Kokoro is not installed.  Run:\n"
                "  pip install kokoro>=0.9.2 soundfile\n"
                "  pip install torch  (or torch with MPS support)"
            ) from exc

        # Choose the best available device for Apple Silicon.
        if torch.backends.mps.is_available():
            device = "mps"
            log.info("Kokoro: using Apple MPS (Metal) GPU")
        elif torch.cuda.is_available():
            device = "cuda"
            log.info("Kokoro: using CUDA GPU")
        else:
            device = "cpu"
            log.info("Kokoro: using CPU")

        log.info("Loading Kokoro pipeline (voice=%s, speed=%.1f)…", self._voice, self._speed)
        try:
            pipeline = KPipeline(lang_code=self._lang_code, device=device)
        except TypeError:
            # Older versions of Kokoro don't accept `device` directly.
            pipeline = KPipeline(lang_code=self._lang_code)

        return pipeline

    @property
    def sample_rate(self) -> int:
        return self._SAMPLE_RATE

    def synthesize(self, chunks: List[str], progress_desc: str = "") -> np.ndarray:
        from tqdm import tqdm

        audio_parts: List[np.ndarray] = []

        for chunk in tqdm(chunks, desc=progress_desc or "Kokoro", unit="chunk"):
            if not chunk.strip():
                continue
            try:
                generator = self._pipeline(
                    chunk,
                    voice=self._voice,
                    speed=self._speed,
                )
                for _, _, audio in generator:
                    if audio is not None and len(audio) > 0:
                        audio_parts.append(
                            audio if isinstance(audio, np.ndarray) else np.array(audio)
                        )
            except Exception as exc:
                log.error("Kokoro synthesis error: %s", exc)
                raise

        if not audio_parts:
            return np.array([], dtype=np.float32)

        return np.concatenate(audio_parts).astype(np.float32)

    def synthesize_iter(self, chunks: List[str], progress_desc: str = ""):
        from tqdm import tqdm
        for chunk in tqdm(chunks, desc=progress_desc or "Kokoro", unit="chunk"):
            if not chunk.strip():
                continue
            try:
                parts = []
                for _, _, audio in self._pipeline(chunk, voice=self._voice, speed=self._speed):
                    if audio is not None and len(audio) > 0:
                        parts.append(audio if isinstance(audio, np.ndarray) else np.array(audio))
                if parts:
                    yield np.concatenate(parts).astype(np.float32)
            except Exception as exc:
                log.error("Kokoro synthesis error: %s", exc)
                raise


# ── Piper backend ──────────────────────────────────────────────────────────────

# Well-known Piper voices with their download URLs.
# Full list at https://github.com/rhasspy/piper/blob/master/VOICES.md
_PIPER_VOICE_URLS: dict[str, tuple[str, str]] = {
    # (onnx_url, config_url)
    "en_US-amy-medium": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json",
    ),
    "en_US-lessac-high": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/high/en_US-lessac-high.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/high/en_US-lessac-high.onnx.json",
    ),
    "en_GB-alan-medium": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json",
    ),
    "en_US-ryan-high": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json",
    ),
}


class PiperBackend(LocalTTSBackend):
    """
    Piper TTS — very fast, CPU-only, no GPU required.

    On first use the selected voice model (~60–200 MB ONNX file) is
    automatically downloaded to config.LOCAL_TTS_PIPER_MODEL_DIR.

    Voice choices (add more to _PIPER_VOICE_URLS above as needed):
        en_US-amy-medium     (default, female)
        en_US-lessac-high    (male, high quality)
        en_GB-alan-medium    (British male)
        en_US-ryan-high      (male, high quality)
    """

    def __init__(self, voice: str = config.LOCAL_TTS_PIPER_VOICE) -> None:
        self._voice_name = voice
        self._model_dir = Path(config.LOCAL_TTS_PIPER_MODEL_DIR)
        self._model_dir.mkdir(parents=True, exist_ok=True)
        self._voice = self._load_voice()

    def _load_voice(self):
        try:
            from piper.voice import PiperVoice
        except ImportError as exc:
            raise ImportError(
                "Piper TTS is not installed.  Run:\n"
                "  pip install piper-tts"
            ) from exc

        onnx_path = self._model_dir / f"{self._voice_name}.onnx"
        cfg_path = self._model_dir / f"{self._voice_name}.onnx.json"

        if not onnx_path.exists() or not cfg_path.exists():
            self._download_voice(onnx_path, cfg_path)

        log.info("Loading Piper voice from %s", onnx_path)
        return PiperVoice.load(str(onnx_path), config_path=str(cfg_path))

    def _download_voice(self, onnx_path: Path, cfg_path: Path) -> None:
        if self._voice_name not in _PIPER_VOICE_URLS:
            known = ", ".join(_PIPER_VOICE_URLS)
            raise ValueError(
                f"Unknown Piper voice '{self._voice_name}'.  "
                f"Known voices: {known}"
            )
        onnx_url, cfg_url = _PIPER_VOICE_URLS[self._voice_name]

        log.info("Downloading Piper voice '%s'…", self._voice_name)
        for url, dest in [(onnx_url, onnx_path), (cfg_url, cfg_path)]:
            log.info("  %s → %s", url, dest.name)
            urllib.request.urlretrieve(url, dest)
        log.info("Voice download complete.")

    @property
    def sample_rate(self) -> int:
        return self._voice.config.sample_rate

    def synthesize(self, chunks: List[str], progress_desc: str = "") -> np.ndarray:
        import io

        from tqdm import tqdm

        audio_parts: List[np.ndarray] = []

        for chunk in tqdm(chunks, desc=progress_desc or "Piper", unit="chunk"):
            if not chunk.strip():
                continue

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav_out:
                self._voice.synthesize(chunk, wav_out)

            buf.seek(0)
            with wave.open(buf, "rb") as wav_in:
                raw = wav_in.readframes(wav_in.getnframes())
                arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

            audio_parts.append(arr)

        if not audio_parts:
            return np.array([], dtype=np.float32)

        return np.concatenate(audio_parts)


# ── Factory ────────────────────────────────────────────────────────────────────

def get_backend(name: str) -> LocalTTSBackend:
    """
    Return an initialised LocalTTSBackend by name.

    Args:
        name: "kokoro" or "piper"
    """
    name = name.strip().lower()
    if name == "kokoro":
        return KokoroBackend()
    if name == "piper":
        return PiperBackend()
    raise ValueError(
        f"Unknown local TTS backend '{name}'.  Choose 'kokoro' or 'piper'."
    )


# ── WAV writer helper ──────────────────────────────────────────────────────────

def write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    """Write a float32 numpy audio array to a 16-bit PCM WAV file."""
    pcm = np.clip(audio, -1.0, 1.0)
    pcm_int16 = (pcm * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)  # 16-bit
        wav_out.setframerate(sample_rate)
        wav_out.writeframes(pcm_int16.tobytes())
