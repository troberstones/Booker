"""
filter.py — Replace profanity in scraped text with clean alternatives.

The replacement list covers common English swear words and their common
misspellings/variants.  Each word is replaced with a semantically similar
clean word so the prose still reads naturally.

Usage:
    from filter import clean_text
    clean = clean_text(raw_text)
"""

from __future__ import annotations

import re
from pathlib import Path

import config

# ── Replacement dictionary ─────────────────────────────────────────────────────
# Keys are lower-case patterns (plain strings — no regex needed for most).
# Values are clean replacements.
#
# Sorted roughly by severity so review is easy.  Add more as needed.

REPLACEMENTS: dict[str, str] = {
    # F-word family
    "fuck":         "screw",
    "fucked":       "screwed",
    "fucker":       "scoundrel",
    "fuckers":      "scoundrels",
    "fucking":      "blasted",
    "fuckin":       "blasted",
    "fuckin'":      "blasted",
    "fucks":        "screws",
    "f*ck":         "screw",
    "f**k":         "screw",
    "fck":          "screw",
    # S-word family
    "shit":         "crud",
    "shits":        "crud",
    "shitty":       "lousy",
    "shitting":     "mucking",
    "shitter":      "wretch",
    "sh*t":         "crud",
    "sh!t":         "crud",
    # A-word family
    "ass":          "rear",
    "asses":        "rears",
    "asshole":      "jerk",
    "assholes":     "jerks",
    "asshat":       "fool",
    "asshead":      "blockhead",
    "a**":          "rear",
    # B-word family
    "bastard":      "wretch",
    "bastards":     "wretches",
    "bitch":        "witch",
    "bitches":      "witches",
    "bitchy":       "snippy",
    "bitching":     "complaining",
    "b*tch":        "witch",
    # D-word family
    "damn":         "dang",
    "damned":       "blasted",
    "damnit":       "dang it",
    "goddamn":      "goodness",
    "goddamned":    "wretched",
    "goddam":       "goodness",
    "god damn":     "goodness",
    # C-word family
    "crap":         "junk",
    "crappy":       "lousy",
    "crapping":     "messing",
    "cunt":         "wretch",
    "cunts":        "wretches",
    "c*nt":         "wretch",
    # P-word family
    "piss":         "tick",
    "pissed":       "furious",
    "pissed off":   "furious",
    "pissing":      "ticking",
    # H-word
    "hell":         "heck",
    "hellhole":     "pit",
    # Misc
    "whore":        "harlot",
    "whores":       "harlots",
    "slut":         "rogue",
    "sluts":        "rogues",
    "dick":         "fool",
    "dicks":        "fools",
    "dickhead":     "blockhead",
    "cock":         "rooster",
    "cocks":        "roosters",
    "cocksucker":   "scoundrel",
    "wank":         "fool around",
    "wanker":       "idiot",
    "wankers":      "idiots",
    "twat":         "fool",
    "twats":        "fools",
    "bugger":       "bother",
    "buggered":     "ruined",
    "arse":         "rear",
    "arsehole":     "jerk",
    "bloody hell":  "blimey",
    "sodding":      "blasted",
    "sod off":      "get lost",
    "bollocks":     "nonsense",
    "whoreson":     "scoundrel",
    "bastardly":    "wretchedly",
}

# ── Compiled regex ─────────────────────────────────────────────────────────────

def _build_pattern(replacements: dict[str, str]) -> re.Pattern[str]:
    """
    Build a single compiled regex that matches all keys as whole words,
    longest keys first (so "pissed off" matches before "pissed").
    """
    # Sort by length descending so longer phrases match first.
    keys_sorted = sorted(replacements.keys(), key=len, reverse=True)
    escaped = [re.escape(k) for k in keys_sorted]
    pattern = r"\b(?:" + "|".join(escaped) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


_PATTERN = _build_pattern(REPLACEMENTS)


def _replace_match(match: re.Match) -> str:
    """Return the clean replacement, preserving the original capitalisation style."""
    original = match.group(0)
    replacement = REPLACEMENTS[original.lower()]

    if original.isupper():
        return replacement.upper()
    if original[0].isupper():
        return replacement.capitalize()
    return replacement


def clean_text(text: str) -> str:
    """Return *text* with all profanity replaced by clean alternatives."""
    return _PATTERN.sub(_replace_match, text)


# ── File-level helpers ─────────────────────────────────────────────────────────

def clean_file(input_path: Path, output_path: Path | None = None) -> Path:
    """
    Read a text file, clean its contents, and write the result.

    If *output_path* is None the file is cleaned in-place.
    Returns the path that was written.
    """
    raw = input_path.read_text(encoding="utf-8")
    cleaned = clean_text(raw)

    dest = output_path if output_path is not None else input_path
    dest.write_text(cleaned, encoding="utf-8")
    return dest


def clean_books_dir() -> None:
    """Clean every .txt file found under config.BOOKS_DIR in-place."""
    books_dir = Path(config.BOOKS_DIR)
    txt_files = list(books_dir.rglob("*.txt"))
    print(f"Cleaning {len(txt_files)} text file(s)…")
    for path in txt_files:
        clean_file(path)
        print(f"  Cleaned: {path.relative_to(books_dir)}")
    print("Filtering complete.")
