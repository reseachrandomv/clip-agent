"""Turn YouTube caption files, or a local whisper pass, into timed words."""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

from app.config import Settings
from app.models import PipelineError, Word

logger = logging.getLogger(__name__)

_TIME = re.compile(
    r"(?:(?P<h>\d+):)?(?P<m>\d{1,2}):(?P<s>\d{2})[.](?P<ms>\d{2,3})"
)
_TAG = re.compile(r"<[^>]+>")
_WORD_TAG = re.compile(
    r"<(?:(?P<h>\d+):)?(?P<m>\d{1,2}):(?P<s>\d{2})[.](?P<ms>\d{2,3})><c>(?P<text>.*?)</c>",
    re.DOTALL,
)

_model = None
_model_key: tuple[str, str, str] | None = None
_model_lock = threading.Lock()


def _seconds(match: re.Match) -> float:
    hours = int(match.group("h") or 0)
    millis = match.group("ms")
    fraction = int(millis) / (1000 if len(millis) == 3 else 100)
    return hours * 3600 + int(match.group("m")) * 60 + int(match.group("s")) + fraction


def parse_json3(payload: dict) -> list[Word]:
    """Read YouTube's json3 caption events into a word list."""

    words: list[Word] = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        base = float(event.get("tStartMs") or 0) / 1000.0
        duration = float(event.get("dDurationMs") or 0) / 1000.0
        pieces: list[tuple[float, str]] = []
        for seg in event.get("segs") or []:
            if not isinstance(seg, dict):
                continue
            raw = (seg.get("utf8") or "").replace("\n", " ").strip()
            if not raw:
                continue
            offset = float(seg.get("tOffsetMs") or 0) / 1000.0
            pieces.append((base + offset, raw))
        for index, (start, text) in enumerate(pieces):
            if index + 1 < len(pieces):
                end = pieces[index + 1][0]
            else:
                end = max(start + 0.2, base + duration)
            if end <= start:
                end = start + 0.2
            words.append(Word(start, end, text))
    words.sort(key=lambda word: (word.start, word.end))
    return words


def _explode(start: float, end: float, text: str) -> list[Word]:
    parts = text.split()
    if not parts:
        return []
    span = max(0.2, end - start)
    step = span / len(parts)
    return [
        Word(start + index * step, start + (index + 1) * step, part)
        for index, part in enumerate(parts)
    ]


def parse_vtt(text: str) -> list[Word]:
    """Read a WebVTT file. Word-timed cues keep their timestamps; rolling lines do not repeat."""

    cues: list[tuple[float, float, str, list[Word]]] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    while index < len(lines):
        timing = re.match(
            r"(?P<a>(?:\d+:)?\d{1,2}:\d{2}\.\d{2,3})\s+-->\s+(?P<b>(?:\d+:)?\d{1,2}:\d{2}\.\d{2,3})",
            lines[index].strip(),
        )
        if not timing:
            index += 1
            continue
        start_match = _TIME.search(timing.group("a"))
        end_match = _TIME.search(timing.group("b"))
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].strip():
            body.append(lines[index])
            index += 1
        raw = "\n".join(body).strip()
        if not start_match or not end_match or not raw:
            continue
        start = _seconds(start_match)
        end = _seconds(end_match)
        tagged = [
            Word(_seconds(match), _seconds(match), re.sub(r"\s+", " ", match.group("text")).strip())
            for match in _WORD_TAG.finditer(raw)
            if match.group("text").strip()
        ]
        # Word tags share a start placeholder; give each word the next tag's time as its end.
        if tagged:
            fixed: list[Word] = []
            for word_index, word in enumerate(tagged):
                word_end = tagged[word_index + 1].start if word_index + 1 < len(tagged) else max(word.start + 0.2, end)
                if word_end <= word.start:
                    word_end = word.start + 0.2
                fixed.append(Word(word.start, word_end, word.text))
            plain = " ".join(word.text for word in fixed)
            cues.append((start, end, plain, fixed))
            continue
        plain = re.sub(r"\s+", " ", _TAG.sub("", raw)).strip()
        if plain:
            cues.append((start, end, plain, []))

    kept: list[tuple[float, float, str, list[Word]]] = []
    for cue in cues:
        if kept and cue[2].startswith(kept[-1][2]) and cue[0] <= kept[-1][1] + 0.3:
            kept[-1] = cue
            continue
        if kept and kept[-1][2].startswith(cue[2]) and cue[0] <= kept[-1][1] + 0.3:
            continue
        kept.append(cue)

    words: list[Word] = []
    for start, end, plain, tagged in kept:
        words.extend(tagged or _explode(start, end, plain))
    words.sort(key=lambda word: (word.start, word.end))
    return words


def words_from_file(path: Path) -> list[Word]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() == ".json3":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PipelineError(f"Couldn't read the caption file {path.name}.") from exc
        if not isinstance(payload, dict):
            return []
        return parse_json3(payload)
    return parse_vtt(text)


def transcribe_audio(path: Path, settings: Settings) -> list[Word]:
    """Transcribe with faster-whisper. The model stays loaded for the next job."""

    global _model, _model_key
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise PipelineError(
            "This video has no captions, and faster-whisper is not installed, so it can't be transcribed."
        ) from exc

    cache = settings.data_dir / "models"
    cache.mkdir(parents=True, exist_ok=True)
    key = (settings.whisper_model, settings.whisper_device, settings.whisper_compute_type)
    with _model_lock:
        if _model is None or _model_key != key:
            logger.info("Loading whisper model %s", settings.whisper_model)
            _model = WhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                download_root=str(cache),
            )
            _model_key = key
        model = _model

    segments, _info = model.transcribe(str(path), word_timestamps=True, vad_filter=True)
    words: list[Word] = []
    for segment in segments:
        segment_words = getattr(segment, "words", None) or []
        if segment_words:
            for token in segment_words:
                text = (token.word or "").strip()
                if text:
                    words.append(Word(float(token.start), float(token.end), text))
            continue
        text = (segment.text or "").strip()
        if text:
            words.append(Word(float(segment.start), float(segment.end), text))
    return words
