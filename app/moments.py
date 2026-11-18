"""Pick 3–5 non-overlapping moments from transcript cues and a replay heatmap."""

from __future__ import annotations

from app.copy import build_caption, build_description, build_hook, signal_score, text_between
from app.models import Moment, Word

MIN_CLIP = 15.0
MAX_CLIP = 35.0
_GAP = 0.4


def target_count(duration: float) -> int:
    """How many clips to aim for, given how much video there is."""

    if duration < MIN_CLIP:
        return 1
    fit = int(duration // MIN_CLIP)
    if duration >= 150 and fit >= 5:
        return 5
    if duration >= 100 and fit >= 4:
        return 4
    if fit >= 3:
        return 3
    return max(1, fit)


def maximum_length(duration: float) -> float:
    """Keep a single window short enough that the target number of clips can still fit."""

    count = target_count(duration)
    if count <= 1 or duration <= MAX_CLIP:
        return min(MAX_CLIP, duration) if duration > 0 else MAX_CLIP
    usable = duration - (count - 1) * _GAP
    return min(MAX_CLIP, max(MIN_CLIP, usable / count))


def iter_windows(duration: float) -> list[tuple[float, float]]:
    if duration <= 0:
        return []
    if duration <= MAX_CLIP:
        return [(0.0, round(duration, 2))]
    cap = maximum_length(duration)
    lengths = [length for length in (18.0, 24.0, 30.0, 35.0) if length <= cap + 0.2]
    if not any(abs(length - cap) < 0.5 for length in lengths):
        lengths.append(round(min(MAX_CLIP, cap), 2))
    windows: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for length in lengths:
        start = 0.0
        while start + MIN_CLIP <= duration + 1e-6:
            end = min(duration, start + length)
            if MIN_CLIP - 1e-6 <= end - start <= cap + 0.2:
                key = (round(start, 2), round(end, 2))
                if key not in seen:
                    seen.add(key)
                    windows.append(key)
            start += 5.0
    return windows


def heat_value(heatmap: list[dict] | None, start: float, end: float) -> float | None:
    """Average replay intensity inside the window. None when YouTube sent no heatmap."""

    if not heatmap:
        return None
    weighted = 0.0
    covered = 0.0
    for point in heatmap:
        try:
            point_start = float(point["start_time"])
            point_end = float(point["end_time"])
            value = float(point["value"])
        except (KeyError, TypeError, ValueError):
            continue
        overlap = min(end, point_end) - max(start, point_start)
        if overlap > 0:
            weighted += overlap * value
            covered += overlap
    if covered <= 0:
        return 0.0
    return max(0.0, min(1.0, weighted / covered))


def _speech_score(word_count: int) -> float:
    speech = min(1.0, word_count / 40.0)
    if word_count < 6:
        speech *= 0.35
    return speech


def score_window(text: str, word_count: int, heat: float | None) -> float:
    signal = signal_score(text)
    speech = _speech_score(word_count)
    if heat is None:
        return (0.75 * signal) + (0.25 * speech)
    return (0.50 * heat) + (0.35 * signal) + (0.15 * speech)


def _fits(start: float, end: float, chosen: list[Moment]) -> bool:
    return all(end <= other.start - _GAP or start >= other.end + _GAP for other in chosen)


def rank_moments(
    words: list[Word],
    heatmap: list[dict] | None,
    duration: float,
    title: str = "",
) -> list[Moment]:
    """Every candidate window, best first."""

    ranked: list[Moment] = []
    for start, end in iter_windows(duration):
        snippet = [word for word in words if word.end > start and word.start < end]
        text = text_between(words, start, end)
        heat = heat_value(heatmap, start, end)
        score = score_window(text, len(snippet), heat)
        ranked.append(
            Moment(
                start=start,
                end=end,
                score=round(score, 4),
                hook=build_hook(text),
                description=build_description(text),
                caption=build_caption(text, title=title),
            )
        )
    ranked.sort(key=lambda moment: (-moment.score, moment.start, moment.end))
    return ranked


def take_best(ranked: list[Moment], duration: float) -> list[Moment]:
    """Keep the strongest windows that do not sit on top of each other."""

    target = target_count(duration)
    chosen: list[Moment] = []
    for moment in ranked:
        if len(chosen) >= target:
            break
        if _fits(moment.start, moment.end, chosen):
            chosen.append(moment)
    chosen.sort(key=lambda moment: moment.start)
    return chosen


def select_moments(
    words: list[Word],
    heatmap: list[dict] | None,
    duration: float,
    title: str = "",
) -> list[Moment]:
    """Heuristic moment picker used when no LLM key is configured."""

    return take_best(rank_moments(words, heatmap, duration, title=title), duration)
