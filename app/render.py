"""Render a 1080x1920 clip: blurred fill, centred 16:9, burned-in captions, original audio."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from app.models import PipelineError

logger = logging.getLogger(__name__)

SIZE_LIMIT = 50 * 1024 * 1024
CRF_STEPS = (22, 30, 36)


def next_crf(current: int, size: int, limit: int = SIZE_LIMIT) -> int | None:
    """The next quality step when a render is over the size budget. None when it should stop."""

    if size <= limit:
        return None
    for step in CRF_STEPS:
        if step > current:
            return step
    return None


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise PipelineError("ffmpeg is not installed, so clips can't be rendered.")


def escape_filter_path(path: Path) -> str:
    text = str(path.resolve())
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace(";", r"\;")
    )


def _has_audio(path: Path) -> bool:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return False
    return bool(payload.get("streams"))


def _subtitle_filter(ass_path: Path) -> str:
    ass = escape_filter_path(ass_path)
    fonts = Path("/usr/share/fonts/truetype/dejavu")
    subtitle = f"ass={ass}"
    if fonts.is_dir():
        subtitle += f":fontsdir={escape_filter_path(fonts)}"
    return subtitle


def _filter_graph(ass_path: Path, with_audio: bool, trim_start: float, duration: float) -> str:
    # trim + setpts makes the burned-in hook and captions start at the cut.
    # The blurred branch is a small copy of the frame, scaled back up behind the sharp 16:9.
    start = f"{trim_start:.3f}"
    length = f"{duration:.3f}"
    parts = [
        f"[0:v]trim=start={start}:duration={length},setpts=PTS-STARTPTS,split[vb][vf]",
        "[vb]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,gblur=sigma=10,scale=1080:1920:flags=bilinear[bg]",
        "[vf]scale=1080:-2[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]",
        f"[base]{_subtitle_filter(ass_path)}[v]",
    ]
    if with_audio:
        parts.append(f"[0:a]atrim=start={start}:duration={length},asetpts=PTS-STARTPTS[a]")
    return ";".join(parts)


def _encode(
    source: Path,
    start: float,
    end: float,
    ass_path: Path,
    output: Path,
    *,
    crf: int,
    preset: str,
) -> None:
    duration = max(0.3, end - start)
    # Fast-seek near the cut, then trim inside the filter so caption time starts at 0.
    # An output -ss would drop the opening frames, including the two-second hook.
    fast = max(0.0, start - 10.0)
    fine = max(0.0, start - fast)
    has_audio = _has_audio(source)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{fast:.3f}",
        "-i",
        str(source),
        "-filter_complex",
        _filter_graph(ass_path, has_audio, fine, duration),
        "-map",
        "[v]",
    ]
    if has_audio:
        command += ["-map", "[a]", "-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    command += [
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-threads",
        "2",
        str(output),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0 or not output.is_file():
        detail = (result.stderr or result.stdout or "ffmpeg failed").strip()
        logger.error("ffmpeg failed: %s", detail[-2000:])
        raise PipelineError("Rendering the clip failed. " + detail[-400:])


def _thumbnail(video: Path, thumb: Path, at: float) -> None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, at):.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(thumb),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not thumb.is_file():
        raise PipelineError("Couldn't write a thumbnail for the clip.")


def render_clip(
    source: Path,
    start: float,
    end: float,
    ass_path: Path,
    output: Path,
    thumbnail: Path,
    *,
    preset: str = "veryfast",
    crf: int = 22,
) -> None:
    """Write one vertical mp4 under the size budget, plus a jpg from the first seconds."""

    _require_ffmpeg()
    output.parent.mkdir(parents=True, exist_ok=True)
    current = crf
    while True:
        _encode(source, start, end, ass_path, output, crf=current, preset=preset)
        size = output.stat().st_size
        step = next_crf(current, size)
        if step is None:
            if size > SIZE_LIMIT:
                raise PipelineError("A clip stayed over 50MB after compressing it.")
            break
        logger.info("Clip is %s bytes, re-encoding at crf %s", size, step)
        current = step
    duration = max(0.3, end - start)
    _thumbnail(output, thumbnail, min(1.2, duration / 2))
