"""Burned-in caption cues and the ASS script ffmpeg draws on each clip."""

from __future__ import annotations

from app.models import Cue, Word

_MAX_WORDS = 4
_MAX_CHARS = 24


def cues_for_clip(words: list[Word], clip_start: float, clip_end: float) -> list[Cue]:
    """Short phrase cues, timed from the start of the clip rather than the source."""

    selected = [word for word in words if word.end > clip_start and word.start < clip_end and word.text.strip()]
    selected.sort(key=lambda word: word.start)
    cues: list[Cue] = []
    bucket: list[Word] = []

    def flush() -> None:
        if not bucket:
            return
        text = " ".join(word.text.strip() for word in bucket)
        start = max(0.0, bucket[0].start - clip_start)
        end = max(start + 0.35, bucket[-1].end - clip_start)
        cues.append(Cue(round(start, 2), round(end, 2), text))
        bucket.clear()

    for word in selected:
        if bucket and word.start - bucket[-1].end > 0.45:
            flush()
        bucket.append(word)
        text = " ".join(item.text.strip() for item in bucket)
        if len(bucket) >= _MAX_WORDS or len(text) >= _MAX_CHARS or text.endswith((".", "!", "?")):
            flush()
    flush()

    tightened: list[Cue] = []
    for index, cue in enumerate(cues):
        end = cue.end
        if index + 1 < len(cues):
            end = min(end, cues[index + 1].start)
        if end < cue.start + 0.25:
            end = cue.start + 0.25
        tightened.append(Cue(cue.start, round(end, 2), cue.text))
    return tightened


def ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remainder = seconds % 60
    return f"{hours}:{minutes:02d}:{remainder:05.2f}"


def escape_ass(text: str) -> str:
    cleaned = text.replace("\\", "").replace("{", "(").replace("}", ")")
    cleaned = cleaned.replace("\n", " ").strip()
    return cleaned


def build_ass(cues: list[Cue], hook: str) -> str:
    """1080x1920 ASS script: a hook at the top for two seconds, then phrase captions."""

    hook_line = escape_ass(hook) or "Watch this moment"
    events = [
        f"Dialogue: 0,{ass_timestamp(0)},{ass_timestamp(2)},Hook,,0,0,0,,{hook_line}"
    ]
    for cue in cues:
        if cue.start >= 120:
            continue
        events.append(
            f"Dialogue: 1,{ass_timestamp(cue.start)},{ass_timestamp(max(cue.end, cue.start + 0.25))},Caption,,0,0,0,,{escape_ass(cue.text)}"
        )
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,DejaVu Sans,68,&H004AE1FF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,0,8,70,70,150,1
Style: Caption,DejaVu Sans,74,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,8,0,5,80,80,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header + "\n".join(events) + "\n"
