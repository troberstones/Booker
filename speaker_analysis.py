"""
speaker_analysis.py — Rule-based dialog attribution for multi-voice synthesis.

Splits chapter text into Segments, each tagged with:
  - whether it is narration or dialog
  - the speaker name (if attributable)
  - the speaker's inferred gender ('f', 'm', or None)
  - how many milliseconds of silence to insert after the segment

Usage:
    from speaker_analysis import analyse_chapter, CharacterRegistry, VoiceMap
    registry = CharacterRegistry()
    voice_map = VoiceMap()
    segments = analyse_chapter(chapter_text, registry)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

import config

# ── Regex constants ────────────────────────────────────────────────────────────

# A dialog line is wrapped in straight or curly double quotes.
_DIALOG_RE = re.compile(
    r'(?s)'
    r'(?P<pre>[^\n""\u201c\u201d]*?)'     # narration before the quote
    r'(?P<open>["\u201c])'                  # opening quote char
    r'(?P<dialog>.*?)'                      # dialog content
    r'(?P<close>["\u201d])'                 # closing quote char
    r'(?P<post>[^"\u201c\u201d\n]*)',       # narration after the quote (attribution)
)

# Speech verbs that follow the dialog (e.g. `"…" she said`)
_SPEECH_VERBS = {
    "said", "say", "says", "asked", "ask", "asks", "replied", "reply",
    "replies", "called", "called out", "answered", "answered", "exclaimed",
    "exclaim", "muttered", "mutter", "whispered", "whisper", "shouted",
    "shout", "yelled", "yell", "declared", "declare", "stated", "state",
    "noted", "note", "added", "add", "continued", "continue", "began",
    "begin", "greeted", "greet", "sighed", "sigh", "laughed", "laugh",
    "cried", "cry", "growled", "growl", "snapped", "snap", "breathed",
    "breath", "murmured", "murmur", "hissed", "hiss", "interrupted",
    "interrupt", "called", "call", "spoke", "speak",
}

# Pattern: name then verb — '"…" Alice said' or '"…" the [adjective] Alice said'
_NAME_THEN_VERB_RE = re.compile(
    r'^\s*,?\s*'
    r'(?:the\s+\w+\s+)?'             # optional determiner+adjective
    r'(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)'  # Proper Name (Title Case)
    r'\s+(?P<verb>\w+)',
)

# Pattern: verb then name — '"…" said Alice'
_VERB_THEN_NAME_RE = re.compile(
    r'^\s*,?\s*'
    r'(?P<verb>\w+)'
    r'\s+(?:the\s+\w+\s+)?'         # optional determiner+adjective
    r'(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
)

# Pronoun sets for gender inference (from sentence context around speaker name)
_FEMALE_PRONOUNS_RE = re.compile(r'\b(?:she|her|hers|herself)\b', re.IGNORECASE)
_MALE_PRONOUNS_RE = re.compile(r'\b(?:he|him|his|himself)\b', re.IGNORECASE)

# Scene-break line (identical to audiobook.py)
_SCENE_BREAK_RE = re.compile(r'^[\s*\-─=~]{3,}$')


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class Segment:
    text: str
    is_dialog: bool
    speaker: Optional[str]   # character name, or None for unnamed/narration
    gender: Optional[str]    # 'f', 'm', or None
    pause_ms: int


# ── Character registry ─────────────────────────────────────────────────────────

class CharacterRegistry:
    """
    Accumulates name→gender mappings across chapters.
    First confident assignment wins; never overwritten.
    """

    def __init__(self) -> None:
        self._genders: Dict[str, str] = {}   # name → 'f' | 'm'

    def update(self, name: str, gender: str) -> None:
        if name and gender and name not in self._genders:
            self._genders[name] = gender

    def get_gender(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        return self._genders.get(name)


# ── Voice map ──────────────────────────────────────────────────────────────────

class VoiceMap:
    """
    Assigns a consistent Kokoro voice to each unique speaker.

    - Speaker None / narrator → config.LOCAL_TTS_KOKORO_VOICE
    - Female characters cycle through config.FEMALE_CHARACTER_VOICES
    - Male characters cycle through config.MALE_CHARACTER_VOICES
    - Unknown-gender characters get a female voice (pool is larger)
    """

    def __init__(self) -> None:
        self._assignments: Dict[str, str] = {}   # name → kokoro voice id
        self._female_idx = 0
        self._male_idx = 0

    def get_voice(self, speaker: Optional[str], gender: Optional[str]) -> str:
        if not speaker:
            return config.LOCAL_TTS_KOKORO_VOICE

        if speaker in self._assignments:
            return self._assignments[speaker]

        # Assign a new voice from the appropriate pool
        if gender == "m":
            pool = config.MALE_CHARACTER_VOICES
            voice = pool[self._male_idx % len(pool)]
            self._male_idx += 1
        else:
            # female or unknown → female pool
            pool = config.FEMALE_CHARACTER_VOICES
            voice = pool[self._female_idx % len(pool)]
            self._female_idx += 1

        self._assignments[speaker] = voice
        return voice


# ── Attribution helpers ────────────────────────────────────────────────────────

def _extract_attribution(post_text: str) -> Optional[str]:
    """
    Try to extract a speaker name from the text immediately after a quote.

    Handles:
        , said Alice          → Alice
        , Alice said          → Alice
        , the young Alice replied  → Alice
    Returns None if no attribution found.
    """
    if not post_text.strip():
        return None

    for pattern in (_VERB_THEN_NAME_RE, _NAME_THEN_VERB_RE):
        m = pattern.match(post_text)
        if m:
            verb = m.group("verb").lower().rstrip("s")
            # Accept the match only if the verb is a speech verb
            if verb in _SPEECH_VERBS or verb + "s" in _SPEECH_VERBS:
                name = m.group("name")
                # Reject common false positives (single-word sentences, etc.)
                if len(name) > 2:
                    return name

    return None


def _infer_gender_from_context(name: str, text: str) -> Optional[str]:
    """
    Search `text` for pronouns near `name` to infer gender.
    Returns 'f', 'm', or None.
    """
    # Find all positions of the name in text
    positions = [m.start() for m in re.finditer(re.escape(name), text, re.IGNORECASE)]
    window = 150  # characters either side of the name

    female_count = 0
    male_count = 0
    for pos in positions:
        ctx = text[max(0, pos - window): pos + len(name) + window]
        female_count += len(_FEMALE_PRONOUNS_RE.findall(ctx))
        male_count += len(_MALE_PRONOUNS_RE.findall(ctx))

    if female_count > male_count:
        return "f"
    if male_count > female_count:
        return "m"
    return None


# ── Main analysis function ─────────────────────────────────────────────────────

def analyse_chapter(text: str, registry: CharacterRegistry) -> List[Segment]:
    """
    Split chapter text into Segments with speaker attribution.

    Strategy per paragraph:
    1. Scan for quoted dialog spans.
    2. Extract speaker attribution from text immediately after each quote.
    3. Infer gender from pronoun context in the full paragraph.
    4. Emit narration segments for text outside quotes, dialog segments for text inside.
    """
    segments: List[Segment] = []

    for block in re.split(r'\n\n+', text):
        block = block.strip()
        if not block:
            continue

        # Scene break → silence only
        if _SCENE_BREAK_RE.match(block):
            segments.append(Segment(
                text="",
                is_dialog=False,
                speaker=None,
                gender=None,
                pause_ms=config.AUDIO_SCENE_BREAK_MS,
            ))
            continue

        # Parse the block for dialog spans
        block_segments = _parse_block(block, registry)
        segments.extend(block_segments)

        # Trailing paragraph pause on the last real segment in this block
        if segments and segments[-1].text:
            segments[-1] = Segment(
                text=segments[-1].text,
                is_dialog=segments[-1].is_dialog,
                speaker=segments[-1].speaker,
                gender=segments[-1].gender,
                pause_ms=config.AUDIO_PARAGRAPH_PAUSE_MS,
            )

    return segments


def _parse_block(block: str, registry: CharacterRegistry) -> List[Segment]:
    """
    Parse a single paragraph block into a list of Segments.
    """
    segments: List[Segment] = []
    cursor = 0

    for m in _DIALOG_RE.finditer(block):
        pre = m.group("pre")
        dialog = m.group("dialog").strip()
        post = m.group("post")

        # Narration before the quote
        narration = block[cursor:m.start()] + pre
        narration = narration.strip()
        if narration:
            segments.append(Segment(
                text=narration,
                is_dialog=False,
                speaker=None,
                gender=None,
                pause_ms=config.DIALOG_PAUSE_MS,
            ))

        # Attempt speaker attribution
        speaker = _extract_attribution(post)
        gender = registry.get_gender(speaker)

        # If gender unknown for this speaker, infer from full block
        if speaker and gender is None:
            gender = _infer_gender_from_context(speaker, block)
            if gender:
                registry.update(speaker, gender)

        # Dialog segment
        if dialog:
            segments.append(Segment(
                text=dialog,
                is_dialog=True,
                speaker=speaker,
                gender=gender,
                pause_ms=config.DIALOG_PAUSE_MS,
            ))

        cursor = m.end()

    # Remaining narration after last quote
    tail = block[cursor:].strip()
    if tail:
        segments.append(Segment(
            text=tail,
            is_dialog=False,
            speaker=None,
            gender=None,
            pause_ms=config.DIALOG_PAUSE_MS,
        ))

    # If no dialog was found in this block, return the whole block as narration
    if not segments:
        segments.append(Segment(
            text=block,
            is_dialog=False,
            speaker=None,
            gender=None,
            pause_ms=config.AUDIO_PARAGRAPH_PAUSE_MS,
        ))

    return segments
