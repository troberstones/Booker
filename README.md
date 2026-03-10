# Booker — Wandering Inn → Cleaned Text → Audiobook

A three-stage pipeline that:

1. **Scrapes** every chapter from [The Wandering Inn](https://wanderinginn.com/table-of-contents/) slowly and politely.
2. **Filters** the downloaded text, replacing swear words with clean alternatives.
3. **Generates** an MP3 audiobook per volume — via OpenAI TTS (cloud) or a fully local AI model (free, offline).

---

## Prerequisites

| Requirement | macOS | Linux |
|---|---|---|
| Python 3.10+ | `brew install python` | `sudo apt install python3` |
| ffmpeg | `brew install ffmpeg` | `sudo apt install ffmpeg` |
| git | pre-installed | `sudo apt install git` |

Check your Python version:

```bash
python3 --version   # must be 3.10 or higher
```

---

## Quick start

Choose **Option A** (OpenAI — paid, any machine) or **Option B** (local — free, Apple M-series).

---

### Option A — OpenAI TTS (cloud)

**Step 1 — Clone the repo and install dependencies**

```bash
git clone <repo-url>
cd Booker
pip install -r requirements.txt
```

**Step 2 — Set your OpenAI API key**

```bash
export OPENAI_API_KEY="sk-..."
```

To make this permanent, add the line above to your `~/.zshrc` (macOS) or `~/.bashrc` (Linux) and run `source ~/.zshrc`.

**Step 3 — Run the full pipeline**

```bash
python main.py
```

This will scrape all chapters, clean the text, and generate one MP3 per volume.
Finished files appear in `output/audio/`.

---

### Option B — Local TTS on Apple M-series (free, offline)

No API key. Runs entirely on your Mac using the Metal GPU.

**Step 1 — Clone the repo and install base dependencies**

```bash
git clone <repo-url>
cd Booker
pip install -r requirements.txt
```

**Step 2 — Install PyTorch with Apple MPS support**

```bash
pip install torch torchvision torchaudio
```

The standard macOS wheel already includes Metal (MPS) support — no extra flags needed.

**Step 3 — Install the Kokoro TTS package**

```bash
pip install -r requirements-local-tts.txt
```

Kokoro (~330 MB) downloads its model automatically the first time it runs.

**Step 4 — Run the full pipeline**

```bash
python main.py --local-tts kokoro
```

This will scrape all chapters, clean the text, and generate one MP3 per volume using your M-series GPU.
Finished files appear in `output/audio/`.

> **Piper fallback (CPU-only, no GPU needed)**
>
> If you prefer a lighter-weight option:
> ```bash
> pip install piper-tts
> python main.py --local-tts piper
> ```
> Piper downloads its ~100 MB ONNX voice file automatically on first run.

---

## Running individual stages

You can run each stage on its own. This is useful for re-generating audio after
tweaking settings without re-scraping, or for filtering text you already have.

```bash
# Stage 1 only — download chapters to output/books/
python main.py --scrape-only

# Stage 2 only — clean swear words in output/books/ (run after scraping)
python main.py --filter-only

# Stage 3 only — generate audio from output/books/ (run after filtering)
python main.py --audio-only                         # OpenAI
python main.py --audio-only --local-tts kokoro      # local Kokoro
python main.py --audio-only --local-tts piper       # local Piper
```

---

## All command-line flags

```
python main.py [--scrape-only | --filter-only | --audio-only]
               [--local-tts {kokoro,piper}]
               [--no-resume]
               [--log-level {DEBUG,INFO,WARNING,ERROR}]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--local-tts kokoro` | — | Use Kokoro-82M local model (Apple MPS GPU, 24 kHz) |
| `--local-tts piper` | — | Use Piper local model (CPU-only, 22 kHz) |
| `--scrape-only` | — | Run stage 1 only |
| `--filter-only` | — | Run stage 2 only |
| `--audio-only` | — | Run stage 3 only |
| `--no-resume` | off | Re-download / re-generate even if output files exist |
| `--log-level` | `INFO` | Logging verbosity |

---

## TTS engine comparison

| | OpenAI `tts-1-hd` | Kokoro-82M (local) | Piper (local) |
|---|---|---|---|
| Cost | ~$15 / million chars | Free | Free |
| Internet required | Yes | No | No |
| GPU | Cloud | Apple MPS (M-series) | CPU only |
| Quality | Excellent | Excellent | Good |
| Speed on M4 Max | Fast (API latency) | Very fast | Very fast |
| Sample rate | 24 kHz | 24 kHz | 22 kHz |
| Model size | — | ~330 MB (auto-download) | ~100 MB ONNX (auto-download) |

---

## Output layout

```
output/
├── books/
│   ├── 01_Volume 1/               # Individual chapter .txt files
│   │   ├── 0001_Prologue.txt
│   │   ├── 0002_Chapter_1_00.txt
│   │   └── ...
│   ├── 01_Volume 1.txt            # Merged + filtered volume file
│   ├── 02_Volume 2/
│   ├── 02_Volume 2.txt
│   └── ...
├── audio/
│   ├── 01_Volume 1.mp3
│   ├── 02_Volume 2.mp3
│   └── ...
└── piper_models/                  # Piper ONNX files (auto-downloaded)
    └── en_US-lessac-high.onnx
```

---

## Configuration

All settings live in `config.py`. Common things to change:

**Scraping**

| Setting | Default | Description |
|---------|---------|-------------|
| `SCRAPE_DELAY_MIN` / `MAX` | `3.0` / `7.0` s | Random pause between chapter requests |

**OpenAI TTS**

| Setting | Default | Description |
|---------|---------|-------------|
| `TTS_MODEL` | `tts-1-hd` | `tts-1` (cheaper) or `tts-1-hd` (higher quality) |
| `TTS_VOICE` | `nova` | `alloy` `echo` `fable` `onyx` `nova` `shimmer` |
| `TTS_CHUNK_SIZE` | `4000` chars | Max characters per API call |

**Local TTS — Kokoro**

| Setting | Default | Description |
|---------|---------|-------------|
| `LOCAL_TTS_KOKORO_VOICE` | `af_heart` | Voice ID (see table below) |
| `LOCAL_TTS_KOKORO_SPEED` | `0.95` | Speaking rate — `1.0` = normal, `0.9` = slightly slower |

**Local TTS — Piper**

| Setting | Default | Description |
|---------|---------|-------------|
| `LOCAL_TTS_PIPER_VOICE` | `en_US-lessac-high` | Voice ID (see table below) |
| `LOCAL_TTS_PIPER_MODEL_DIR` | `output/piper_models` | Where ONNX files are cached |

### Kokoro voice options

| Voice ID | Style |
|----------|-------|
| `af_heart` | American female — warm (default) |
| `af_bella` | American female — expressive |
| `af_nicole` | American female — calm |
| `am_adam` | American male |
| `am_michael` | American male |
| `bf_emma` | British female |
| `bf_isabella` | British female |
| `bm_george` | British male |
| `bm_lewis` | British male |

### Piper voice options

| Voice ID | Style |
|----------|-------|
| `en_US-lessac-high` | American male, high quality (default) |
| `en_US-amy-medium` | American female, medium quality |
| `en_US-ryan-high` | American male, high quality |
| `en_GB-alan-medium` | British male, medium quality |

---

## Cost estimate (OpenAI only)

The Wandering Inn is roughly 12 million words (~72 million characters).

| Model | Rate | Total estimate |
|-------|------|----------------|
| `tts-1-hd` | $15 / million chars | ~$1 080 |
| `tts-1` | $7.50 / million chars | ~$540 |

Use `--local-tts kokoro` to generate everything for **free**.

---

## Resuming interrupted runs

By default the pipeline skips files it has already completed:

- **Scraper** — skips chapter `.txt` files that already exist and are non-empty.
- **Audiobook generator** — skips volumes whose `.mp3` already exists.

Start where you left off simply by re-running the same command.
Use `--no-resume` to force everything to be re-downloaded or re-generated from scratch.
