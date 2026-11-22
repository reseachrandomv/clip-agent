"""YouTube caption files become a clean list of timed lines."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Segment:
    start: float
    end: float
    text: str


_CUE_TIME = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s+-->\s+"
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
)
_TAG = re.compile(r"<[^>]+>")
_ENTITY = re.compile(r"&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z]+);")
_NAMED = {"nbsp": " ", "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def _fraction(raw: str) -> float:
    return int(raw) / (10 ** len(raw))


def _stamp(hours: str | None, minutes: str, seconds: str, fraction: str) -> float:
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + _fraction(fraction)


def _entity(match: re.Match[str]) -> str:
    token = match.group(1)
    if token in _NAMED:
        return _NAMED[token]
    try:
        if token.startswith("#x"):
            return chr(int(token[2:], 16))
        if token.startswith("#"):
            return chr(int(token[1:]))
    except (ValueError, OverflowError):
        return " "
    return " "


def clean_caption_text(text: str) -> str:
    text = _TAG.sub("", text)
    text = _ENTITY.sub(_entity, text)
    text = text.replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_vtt(raw: str, *, dedupe: bool = True) -> list[Segment]:
    """Parse a WebVTT (or similarly timed) caption file.

    YouTube's auto-captions repeat a growing line. Deduping is on by default
    because those repeats would otherwise burn in as stacked captions.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    segments: list[Segment] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION", "Kind:", "Language:")):
            continue
        time_at = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if time_at is None:
            continue
        match = _CUE_TIME.search(lines[time_at])
        if not match:
            continue
        start = _stamp(match.group(1), match.group(2), match.group(3), match.group(4))
        end = _stamp(match.group(5), match.group(6), match.group(7), match.group(8))
        cue = clean_caption_text(" ".join(lines[time_at + 1 :]))
        if cue and end > start:
            segments.append(Segment(start, end, cue))
    if dedupe:
        return dedupe_segments(segments)
    return segments


def dedupe_segments(segments: list[Segment]) -> list[Segment]:
    """Collapse the rolling captions YouTube emits as a line grows."""
    kept: list[Segment] = []
    for seg in segments:
        text = clean_caption_text(seg.text)
        if not text:
            continue
        if not kept:
            kept.append(Segment(seg.start, seg.end, text))
            continue
        prev = kept[-1]
        close = seg.start <= prev.end + 0.35
        same_line = text == prev.text or text.startswith(prev.text) or prev.text.startswith(text)
        contained = text in prev.text or prev.text in text
        if close and (same_line or contained):
            if len(text) >= len(prev.text):
                prev.text = text
            prev.start = min(prev.start, seg.start)
            prev.end = max(prev.end, seg.end)
            continue
        kept.append(Segment(seg.start, seg.end, text))
    return kept


def text_between(segments: list[Segment], start: float, end: float) -> str:
    parts: list[str] = []
    for seg in segments:
        if seg.end <= start or seg.start >= end:
            continue
        if seg.text:
            parts.append(seg.text.strip())
    return re.sub(r"\s+", " ", " ".join(parts)).strip()
