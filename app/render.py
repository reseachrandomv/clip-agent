"""Frame a 16:9 source as a 1080x1920 short with burned-in captions."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


class RenderError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    has_audio: bool
    has_video: bool


def probe(path: Path) -> MediaInfo:
    try:
        raw = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,width,height",
                "-of",
                "json",
                str(path),
            ],
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        raise RenderError("Could not read that media file.") from exc
    data = json.loads(raw)
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    width = height = 0
    has_audio = False
    has_video = False
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "audio":
            has_audio = True
        if stream.get("codec_type") == "video" and not has_video:
            has_video = True
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
    return MediaInfo(duration, width, height, has_audio, has_video)


def bitrate_for(duration: float, budget_mb: float = 42.0) -> int:
    """Cap the video rate so a 35s clip stays under about 50MB."""
    audio_bps = 128_000
    bits = budget_mb * 1024 * 1024 * 8
    return max(600_000, int(bits / max(duration, 0.5) - audio_bps))


def _filter_path(path: Path) -> str:
    text = str(path.resolve())
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        tail = detail[-600:] if detail else "ffmpeg failed"
        raise RenderError(tail)


def render_clip(
    source: Path,
    start: float,
    end: float,
    ass_path: Path,
    out_mp4: Path,
    out_jpg: Path,
    *,
    preset: str = "veryfast",
) -> None:
    if end <= start:
        raise RenderError("Clip end must be after the start.")
    duration = end - start
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    info = probe(source)
    if not info.has_video:
        raise RenderError("The source file has no video stream.")

    # Seek near the cut, then trim exactly, so captions stay lined up with speech.
    preroll = 0.0 if start < 0.75 else 0.75
    fast = max(0.0, start - preroll)
    precise = start - fast
    rate = bitrate_for(duration)
    # Landscape source sits in the middle. A scaled, blurred copy fills the 9:16 frame.
    filter_complex = (
        "[0:v]split[vbg][vfg];"
        "[vbg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:2[bg];"
        "[vfg]scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto[framed];"
        f"[framed]ass={_filter_path(ass_path)}[outv]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{fast:.3f}",
        "-i",
        str(source),
        "-ss",
        f"{precise:.3f}",
        "-t",
        f"{duration:.3f}",
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
    ]
    if info.has_audio:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        "21",
        "-maxrate",
        str(rate),
        "-bufsize",
        str(rate * 2),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    _run(cmd)

    if out_mp4.stat().st_size > 50 * 1024 * 1024:
        # One tighter pass if a very busy frame still slipped past the cap.
        tighter = max(400_000, rate // 2)
        cmd[cmd.index("-maxrate") + 1] = str(tighter)
        cmd[cmd.index("-bufsize") + 1] = str(tighter * 2)
        _run(cmd)

    # 1.1s still falls inside the 2s hook, and usually catches the first caption.
    thumb_at = min(1.0, max(0.0, duration / 2))
    # -ss after -i so the jpeg is the frame at that time, not a nearby keyframe.
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(out_mp4),
            "-ss",
            f"{thumb_at:.3f}",
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(out_jpg),
        ]
    )
