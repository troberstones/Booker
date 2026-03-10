# Booker — Wandering Inn → Cleaned Text → Audiobook

A three-stage pipeline that:

1. **Scrapes** every chapter from [The Wandering Inn](https://wanderinginn.com/table-of-contents/) slowly and politely.
2. **Filters** the downloaded text, replacing profanity with clean alternatives.
3. **Generates** MP3 audiobooks for each volume — via OpenAI TTS (cloud) **or** a fully local AI model (free, offline).

---

## Requirements

- Python 3.10+
- `ffmpeg` installed on your system (used by `pydub` for audio concatenation)

```bash
brew install ffmpeg   # macOS
sudo apt install ffmpeg  # Debian/Ubuntu
```

---

## Setup

### Option A — OpenAI TTS (cloud, paid)

High quality, any machine, requires an API key.

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."
python main.py
```

### Option B — Local TTS on Apple M-series (free, offline)

No API key needed. Runs entirely on your Mac using Metal GPU.

#### Kokoro (recommended — best quality)

```bash
pip install -r requirements.txt
pip install -r requirements-local-tts.txt
pip install torch torchvision torchaudio   # standard macOS wheel includes MPS
python main.py --local-tts kokoro
```

Kokoro downloads its ~330 MB model automatically on first run.

#### Piper (lightweight CPU fallback)

```bash
pip install -r requirements.txt
pip install piper-tts
python main.py --local-tts piper
```

Piper downloads its ~100 MB ONNX voice file automatically on first run.

---

## Usage

### Full pipeline

```bash
# OpenAI cloud TTS
python main.py

# Local Kokoro TTS (Apple M-series, recommended)
python main.py --local-tts kokoro

# Local Piper TTS (CPU, lightweight)
python main.py --local-tts piper
```

### Individual stages

```bash
python main.py --scrape-only                        # Download chapters only
python main.py --filter-only                        # Clean text only
python main.py --audio-only                         # OpenAI audio only
python main.py --audio-only --local-tts kokoro      # Local audio only
```

### All flags

| Flag | Description |
|------|-------------|
| `--local-tts kokoro` | Use Kokoro-82M local model (Apple MPS GPU, 24 kHz) |
| `--local-tts piper` | Use Piper local model (CPU-only, 22 kHz) |
| `--no-resume` | Re-download / re-generate even if output files exist |
| `--log-level DEBUG` | Verbose logging |

---

## TTS engine comparison

| | OpenAI `tts-1-hd` | Kokoro-82M (local) | Piper (local) |
|---|---|---|---|
| Cost | ~$15/M chars | Free | Free |
| Internet required | Yes | No | No |
| GPU | Cloud | Apple MPS (M-series) | CPU only |
| Quality | Excellent | Excellent | Good |
| Speed on M4 Max | Fast (API) | Very fast | Very fast |
| Sample rate | 24 kHz | 24 kHz | 22 kHz |

---

## Output layout

```
output/
├── books/
│   ├── 01_Volume 1/                   # Individual chapter .txt files
│   │   ├── 0001_Prologue.txt
│   │   └── ...
│   ├── 01_Volume 1.txt                # Merged + filtered volume file
│   └── ...
├── audio/
│   ├── 01_Volume 1.mp3
│   └── ...
└── piper_models/                      # Auto-downloaded Piper ONNX files
    └── en_US-lessac-high.onnx
```

---

## Configuration

Edit `config.py` to change any setting:

**OpenAI TTS**
| Setting | Default | Description |
|---------|---------|-------------|
| `TTS_MODEL` | `tts-1-hd` | `tts-1` (cheaper) or `tts-1-hd` (higher quality) |
| `TTS_VOICE` | `nova` | `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer` |
| `TTS_CHUNK_SIZE` | 4 000 chars | Max chars per API call |

**Local TTS (Kokoro)**
| Setting | Default | Description |
|---------|---------|-------------|
| `LOCAL_TTS_KOKORO_VOICE` | `af_heart` | See voice list below |
| `LOCAL_TTS_KOKORO_SPEED` | `0.95` | Speaking rate (1.0 = normal) |

**Local TTS (Piper)**
| Setting | Default | Description |
|---------|---------|-------------|
| `LOCAL_TTS_PIPER_VOICE` | `en_US-lessac-high` | See voice list below |
| `LOCAL_TTS_PIPER_MODEL_DIR` | `output/piper_models` | Where ONNX files are cached |

**Kokoro voices**

| Voice ID | Description |
|----------|-------------|
| `af_heart` | American female — warm (default) |
| `af_bella` | American female — expressive |
| `am_adam` | American male |
| `am_michael` | American male |
| `bf_emma` | British female |
| `bm_george` | British male |

**Piper voices** (pre-configured in `local_tts.py`)

| Voice ID | Description |
|----------|-------------|
| `en_US-lessac-high` | American male, high quality (default) |
| `en_US-amy-medium` | American female, medium quality |
| `en_GB-alan-medium` | British male, medium quality |
| `en_US-ryan-high` | American male, high quality |

---

## Cost estimate (OpenAI)

The Wandering Inn is ~12 million words (~72 million characters).
- `tts-1-hd`: ~$15/M chars → ~**$1 080** for all volumes
- `tts-1`: ~$7.50/M chars → ~**$540** for all volumes

Use `--local-tts kokoro` to generate everything for **free**.

---

## Resuming interrupted runs

By default the pipeline resumes where it left off:
- The scraper skips chapter files that already exist and are non-empty.
- The audiobook generator skips volumes whose MP3 already exists.

Use `--no-resume` to force a full re-run.
