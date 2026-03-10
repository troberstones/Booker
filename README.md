# Booker — Wandering Inn → Cleaned Text → Audiobook

A three-stage pipeline that:

1. **Scrapes** every chapter from [The Wandering Inn](https://wanderinginn.com/table-of-contents/) slowly and politely.
2. **Filters** the downloaded text, replacing profanity with clean alternatives.
3. **Generates** MP3 audiobooks for each volume using OpenAI's TTS API.

---

## Requirements

- Python 3.10+
- `ffmpeg` installed on your system (used by `pydub` for audio concatenation)
- An OpenAI API key with access to the TTS API

### Install Python dependencies

```bash
pip install -r requirements.txt
```

### Install ffmpeg

```bash
# Debian / Ubuntu
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

---

## Setup

Export your OpenAI API key before running:

```bash
export OPENAI_API_KEY="sk-..."
```

---

## Usage

### Full pipeline (scrape → filter → audiobook)

```bash
python main.py
```

### Individual stages

```bash
python main.py --scrape-only     # Download chapters only
python main.py --filter-only     # Clean text only (run after scraping)
python main.py --audio-only      # Generate audio only (run after filtering)
```

### Options

| Flag | Description |
|------|-------------|
| `--no-resume` | Re-download / re-generate even if output files exist |
| `--log-level DEBUG` | Verbose logging |

---

## Output layout

```
output/
├── books/
│   ├── 01_Volume 1/                   # Individual chapter .txt files
│   │   ├── 0001_Prologue.txt
│   │   ├── 0002_Chapter_1_00.txt
│   │   └── ...
│   ├── 01_Volume 1.txt                # Merged volume file (filtered in-place)
│   └── ...
└── audio/
    ├── 01_Volume 1.mp3
    └── ...
```

---

## Configuration

Edit `config.py` to change:

| Setting | Default | Description |
|---------|---------|-------------|
| `SCRAPE_DELAY_MIN/MAX` | 3 – 7 s | Random pause between chapter requests |
| `TTS_MODEL` | `tts-1-hd` | `tts-1` (faster) or `tts-1-hd` (higher quality) |
| `TTS_VOICE` | `nova` | `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer` |
| `TTS_CHUNK_SIZE` | 4 000 chars | Max characters per TTS API call |

---

## Cost estimate

The Wandering Inn is ~12 million words (~72 million characters).  At the
time of writing, OpenAI TTS costs **$15 per 1 million characters** for
`tts-1-hd`.  Generating all volumes would cost roughly **$1 080**.  Consider
using `tts-1` ($7.50 / 1M chars) for a cheaper draft, or processing one
volume at a time with `--audio-only` on just the desired file.

---

## Resuming interrupted runs

By default the pipeline resumes where it left off:
- The scraper skips chapter files that already exist and are non-empty.
- The audiobook generator skips volumes whose MP3 already exists.

Use `--no-resume` to force a full re-run.
