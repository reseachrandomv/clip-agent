"""ASS subtitles: a top hook for two seconds, then big bottom captions."""

from __future__ import annotations

from pathlib import Path

from app.transcript import Segment

_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,64,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,8,0,2,90,90,300,1
Style: Hook,DejaVu Sans,60,&H00FFFFFF,&H000000FF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,6,0,8,70,70,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_time(seconds: float) -> str:
    total = int(round(max(0.0, seconds) * 100))
    hours, rem = divmod(total, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _escape(text: str) -> str:
    parts = []
    for line in text.split("\n"):
        line = line.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        parts.append(line)
    return "\\N".join(parts)


def _cues(text: str, width: int = 22) -> list[str]:
    """Break a line into cues of at most two wrapped lines, so nothing sits alone."""
    words = text.split()
    cues: list[str] = []
    lines: list[str] = []
    current: list[str] = []

    def flush_line() -> None:
        nonlocal current
        if current:
            lines.append(" ".join(current))
            current = []

    def flush_cue() -> None:
        nonlocal lines
        flush_line()
        if lines:
            cues.append("\n".join(lines))
            lines = []

    for word in words:
        trial = " ".join(current + [word])
        if current and len(trial) > width:
            flush_line()
            if len(lines) == 2:
                flush_cue()
            current = [word]
        else:
            current.append(word)
    flush_cue()
    return cues


def write_ass(
    path: Path,
    *,
    segments: list[Segment],
    hook: str,
    clip_start: float,
    clip_end: float,
) -> None:
    clip_length = max(0.0, clip_end - clip_start)
    events: list[str] = []
    if hook.strip() and clip_length > 0:
        hook_end = min(2.0, clip_length)
        events.append(
            f"Dialogue: 0,{ass_time(0)},{ass_time(hook_end)},Hook,,0,0,0,,{_escape(hook.strip())}"
        )
    for seg in segments:
        if seg.end <= clip_start or seg.start >= clip_end:
            continue
        rel_start = max(0.0, seg.start - clip_start)
        rel_end = min(clip_length, seg.end - clip_start)
        if rel_end - rel_start < 0.15:
            continue
        pieces = _cues(seg.text)
        if not pieces:
            continue
        step = (rel_end - rel_start) / len(pieces)
        for index, piece in enumerate(pieces):
            start = rel_start + index * step
            end = rel_start + (index + 1) * step
            events.append(
                f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{_escape(piece)}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_HEADER + "\n".join(events) + "\n", encoding="utf-8")
