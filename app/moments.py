"""Pick 15–35s moments from heatmap peaks and transcript signals."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.transcript import Segment

MIN_CLIP = 15.0
MAX_CLIP = 35.0

_WORD = re.compile(r"[A-Za-z0-9']+")
_LAUGH = re.compile(r"(ha){2,}|hehe|haha|lol+|lmao|\blaugh", re.IGNORECASE)
_REACT = re.compile(
    r"\b(wow|omg|oh my god|no way|insane|unbelievable|what the|lets go|let's go)\b",
    re.IGNORECASE,
)
_PUNCH = re.compile(r"\b(because|actually|that's|that is)\b", re.IGNORECASE)
_STOP = {
    "that", "this", "with", "from", "have", "your", "just", "what", "when", "where",
    "were", "been", "they", "them", "then", "than", "into", "about", "because",
    "would", "could", "should", "there", "their", "here", "going", "gonna",
    "really", "watch", "shorts", "video", "clip", "like", "subscribe", "welcome",
    "back", "channel", "will", "cant", "don't", "dont", "ever", "never", "seen",
    "thing", "today", "whole", "time", "the", "and", "for", "you", "are", "was",
    "did", "its", "his", "her", "she", "him", "our", "out", "not", "but", "all",
    "can", "get", "got", "let", "why", "how", "who", "too", "very", "really",
}


@dataclass
class HeatPoint:
    start: float
    end: float
    value: float


@dataclass
class Moment:
    start: float
    end: float
    score: float
    hook: str
    description: str
    caption: str
    signals: list[str]


def word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


def signal_labels(text: str) -> list[str]:
    labels: list[str] = []
    if _LAUGH.search(text or ""):
        labels.append("laughter")
    caps = re.findall(r"\b[A-Z]{3,}\b", text or "")
    if caps or (text or "").count("!") >= 2:
        labels.append("shouting")
    if _REACT.search(text or ""):
        labels.append("reaction")
    if "?" in (text or "") and _PUNCH.search(text or ""):
        labels.append("punchline")
    return labels


def text_signal(text: str) -> float:
    if not text:
        return 0.0
    score = 0.0
    score += 2.4 * len(_LAUGH.findall(text))
    score += 1.8 * len(_REACT.findall(text))
    score += min(2.0, text.count("!") * 0.7)
    score += min(1.5, text.count("?") * 0.5)
    score += min(2.5, 0.7 * len(re.findall(r"\b[A-Z]{3,}\b", text)))
    if "?" in text and _PUNCH.search(text):
        score += 1.6
    return score


def make_hook(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return "Watch this"
    pieces = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", cleaned) if part.strip()]
    best = max(pieces or [cleaned], key=lambda part: (text_signal(part), -word_count(part)))
    words = _WORD.findall(best) or _WORD.findall(cleaned)
    if not words:
        return "Watch this"
    return " ".join(words[:7])


def describe(text: str, labels: list[str]) -> str:
    quote = re.sub(r"\s+", " ", text or "").strip()
    if len(quote) > 140:
        cut = quote[:140]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        quote = cut.rstrip(".,;:") + "…"
    if not quote:
        return "A highlight from the video."
    leads = {
        "laughter": "Laughter breaks out",
        "shouting": "The energy spikes",
        "reaction": "A strong reaction lands",
        "punchline": "A punchline lands",
    }
    for key in ("laughter", "shouting", "reaction", "punchline"):
        if key in labels:
            return f"{leads[key]}: {quote}"
    return f"A highlight moment: {quote}"


def hashtags_for(text: str) -> list[str]:
    tags = ["#shorts", "#youtubeshorts"]
    seen: set[str] = set()
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", (text or "").lower()):
        if word in _STOP or word in seen or word.startswith("hah"):
            continue
        seen.add(word)
        tags.append("#" + word)
        if len(tags) >= 5:
            break
    return tags


def share_caption(hook: str, description: str, text: str) -> str:
    tags = " ".join(hashtags_for(f"{hook} {text}"))
    return f"{hook}\n\n{description}\n\n{tags}"


def plan_shape(duration: float) -> tuple[int, float]:
    """How many clips, and how long each one is, for a video of this length."""
    if duration <= 0:
        return 0, 0.0
    if duration < MIN_CLIP:
        return 1, duration
    if duration <= MAX_CLIP:
        if duration >= 32:
            length = min(MAX_CLIP, max(MIN_CLIP, duration / 2 * 0.92))
            return 2, length
        return 1, duration

    count = 5
    if duration < 130:
        count = 4
    if duration < 90:
        count = 3
    if duration < 55:
        count = 2
    while count > 1 and duration / count < MIN_CLIP:
        count -= 1
    slot = duration / count
    length = min(MAX_CLIP, max(MIN_CLIP, slot * 0.72))
    while count > 1 and count * length > duration + 1e-6:
        count -= 1
        slot = duration / count
        length = min(MAX_CLIP, max(MIN_CLIP, slot * 0.72))
    return count, length


def heatmap_average(start: float, end: float, heatmap: list[HeatPoint]) -> float:
    """Mean replay intensity across the whole window. Cold seconds count as zero."""
    length = end - start
    if length <= 0 or not heatmap:
        return 0.0
    weighted = 0.0
    for point in heatmap:
        overlap = min(end, point.end) - max(start, point.start)
        if overlap <= 0:
            continue
        weighted += overlap * max(0.0, min(1.0, point.value))
    return weighted / length


def _window_text(segments: list[Segment], start: float, end: float) -> tuple[str, float, float]:
    """Transcript inside the window, its signal, and how late the hot line begins.

    A window that merely brushes a line should not score like one that contains it.
    A hot line should also sit near the start of the clip, where the hook is.
    """
    parts: list[str] = []
    signal = 0.0
    first_hot: float | None = None
    for seg in segments:
        overlap = min(end, seg.end) - max(start, seg.start)
        if overlap <= 0.05:
            continue
        frac = min(1.0, overlap / max(0.2, seg.end - seg.start))
        parts.append(seg.text.strip())
        seg_signal = text_signal(seg.text) * frac
        signal += seg_signal
        if seg_signal >= 1.2:
            delay = max(0.0, seg.start - start)
            if first_hot is None or delay < first_hot:
                first_hot = delay
    text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    lead_penalty = 0.0 if first_hot is None else min(5.0, first_hot * 0.7)
    return text, signal, lead_penalty


def _score(start: float, end: float, text: str, signal: float, lead_penalty: float, heatmap: list[HeatPoint]) -> float:
    heat = heatmap_average(start, end, heatmap)
    labels = signal_labels(text)
    density = min(1.0, len(text) / (max(0.1, end - start) * 8))
    score = heat * 6.0 + signal + density * 1.2 - lead_penalty
    if start < 3 and heat < 0.4:
        score -= 0.8
    if "laughter" in labels:
        score += 0.5
    if "reaction" in labels:
        score += 0.35
    return score


def _moment(start: float, end: float, score: float, text: str) -> Moment:
    labels = signal_labels(text)
    hook = make_hook(text)
    description = describe(text, labels)
    return Moment(
        start=start,
        end=end,
        score=score,
        hook=hook,
        description=description,
        caption=share_caption(hook, description, text),
        signals=labels,
    )


def _candidate_starts(duration: float, length: float, heatmap: list[HeatPoint]) -> list[float]:
    if duration <= length + 0.05:
        return [0.0]
    last = max(0.0, duration - length)
    starts = []
    cursor = 0.0
    while cursor <= last + 1e-6:
        starts.append(cursor)
        cursor += 2.0
    if not starts or last - starts[-1] > 0.5:
        starts.append(last)
    peaks = sorted(heatmap, key=lambda point: point.value, reverse=True)[:8]
    for point in peaks:
        centre = (point.start + point.end) / 2
        starts.append(min(max(0.0, centre - length / 2), last))
    return starts


def select_moments(
    duration: float,
    segments: list[Segment],
    heatmap: list[HeatPoint],
) -> list[Moment]:
    count, length = plan_shape(duration)
    if count == 0:
        return []
    if duration <= length + 0.05:
        text, signal, lead = _window_text(segments, 0.0, duration)
        return [_moment(0.0, duration, _score(0.0, duration, text, signal, lead, heatmap), text)]

    last = max(0.0, duration - length)
    ranked: dict[float, tuple[float, float, float, str]] = {}
    for raw_start in _candidate_starts(duration, length, heatmap):
        start = min(max(0.0, raw_start), last)
        end = min(duration, start + length)
        if duration >= MIN_CLIP and end - start < MIN_CLIP - 0.05:
            start = max(0.0, end - length)
            end = min(duration, start + length)
        key = round(start, 2)
        text, signal, lead = _window_text(segments, start, end)
        score = _score(start, end, text, signal, lead, heatmap)
        current = ranked.get(key)
        if current is None or score > current[0]:
            ranked[key] = (score, start, end, text)

    ordered = sorted(ranked.values(), key=lambda item: (-item[0], item[1]))
    picked: list[Moment] = []
    for score, start, end, text in ordered:
        if any(start < existing.end - 0.05 and end > existing.start + 0.05 for existing in picked):
            continue
        picked.append(_moment(start, end, score, text))
        if len(picked) == count:
            break
    picked.sort(key=lambda moment: moment.start)
    return picked
