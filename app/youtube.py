"""Download a YouTube video and any captions yt-dlp can save beside it."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.models import DownloadResult, PipelineError, Word
from app.transcript import words_from_file

logger = logging.getLogger(__name__)

_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def is_youtube_url(url: str) -> bool:
    """True for a normal watch, short, or youtu.be link with a video id."""

    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if host not in _HOSTS:
        return False
    return _video_id(parsed) is not None


def _video_id(parsed) -> str | None:
    if (parsed.hostname or "").lower().endswith("youtu.be"):
        candidate = parsed.path.strip("/").split("/")[0]
    else:
        parts = [part for part in parsed.path.split("/") if part]
        candidate = ""
        if parts[:1] == ["watch"]:
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif parts[:1] == ["shorts"] and len(parts) >= 2:
            candidate = parts[1]
        elif parts[:1] == ["embed"] and len(parts) >= 2:
            candidate = parts[1]
        elif parts[:1] == ["live"] and len(parts) >= 2:
            candidate = parts[1]
        elif "v" in parse_qs(parsed.query):
            candidate = parse_qs(parsed.query).get("v", [""])[0]
    if len(candidate) < 6 or len(candidate) > 32:
        return None
    if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for char in candidate):
        return None
    return candidate


def _deno_path() -> str | None:
    found = shutil.which("deno")
    if found:
        return found
    sibling = Path(sys.executable).resolve().parent / "deno"
    if sibling.is_file():
        return str(sibling)
    return None


# 720p–1080p when YouTube offers it, and a lower file if that is all that exists.
_FORMAT = (
    "bestvideo[height<=1080][height>=720][vcodec!=none]+bestaudio/"
    "bestvideo[height<=1080][vcodec!=none]+bestaudio/"
    "best[height<=1080]/best"
)


def _run_yt_dlp(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run yt-dlp as a process so a hung connection can be killed."""

    if shutil.which("yt-dlp") is None and not (Path(sys.executable).resolve().parent / "yt-dlp").is_file():
        raise PipelineError("yt-dlp is not installed, so the video can't be downloaded.")
    binary = shutil.which("yt-dlp") or str(Path(sys.executable).resolve().parent / "yt-dlp")
    command = [binary, "--no-update", "--no-progress", "--no-warnings"]
    deno = _deno_path()
    if deno:
        command += ["--js-runtimes", f"deno:{deno}"]
    command += args
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(
            "YouTube didn't respond in time. A datacenter network often gets a bot check or a hung connection. Try again from a normal home connection."
        ) from exc


def _failure_text(result: subprocess.CompletedProcess) -> str:
    text = (result.stderr or result.stdout or "yt-dlp failed").strip()
    text = re.sub(r"\s+", " ", text)
    return text[-400:]


def _load_info(stdout: str) -> dict:
    raw = stdout.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise PipelineError("YouTube returned nothing for that link.")
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise PipelineError("YouTube returned nothing for that link.") from exc
    if not isinstance(payload, dict):
        raise PipelineError("YouTube returned nothing for that link.")
    return payload


def _find_video(dest: Path) -> Path:
    candidates = sorted(dest.glob("source.*"))
    videos = [path for path in candidates if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
    if not videos:
        raise PipelineError("The download finished, but no video file was saved.")
    mp4s = [path for path in videos if path.suffix.lower() == ".mp4"]
    return mp4s[0] if mp4s else videos[0]


def _caption_file(dest: Path) -> Path | None:
    files = [*dest.glob("*.json3"), *dest.glob("*.vtt")]

    def rank(path: Path) -> tuple[int, str]:
        name = path.name.lower()
        score = 0
        if ".en" in name or name.startswith("source.en"):
            score += 4
        if "auto" not in name:
            score += 2
        if path.suffix.lower() == ".json3":
            score += 1
        return (score, name)

    if not files:
        return None
    return max(files, key=rank)


def _load_heatmap(info: dict) -> list[dict]:
    heatmap = info.get("heatmap") or []
    if not isinstance(heatmap, list):
        return []
    cleaned = []
    for point in heatmap:
        if not isinstance(point, dict):
            continue
        try:
            cleaned.append(
                {
                    "start_time": float(point["start_time"]),
                    "end_time": float(point["end_time"]),
                    "value": float(point["value"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return cleaned


def download_video(url: str, dest: Path, settings: Settings) -> DownloadResult:
    """Save the video, its replay heatmap, and caption words when YouTube has them."""

    if not is_youtube_url(url):
        raise PipelineError("Paste a YouTube video link, like https://www.youtube.com/watch?v=…")
    dest.mkdir(parents=True, exist_ok=True)
    probed = _run_yt_dlp(
        ["--skip-download", "--dump-single-json", "--no-playlist", "--socket-timeout", "15", "--retries", "1", url],
        timeout=50,
    )
    if probed.returncode != 0:
        raise PipelineError(f"YouTube didn't allow this download. {_failure_text(probed)}")
    info = _load_info(probed.stdout)
    duration = float(info.get("duration") or 0)
    if duration <= 0:
        raise PipelineError("That link doesn't look like a finished video (it may be a live stream).")
    if duration > settings.max_duration_seconds:
        minutes = settings.max_duration_seconds // 60
        raise PipelineError(
            f"That video is {int(duration // 60)} minutes long. Clip Agent stops at {minutes} minutes so a small server can finish."
        )
    logger.info("Downloading %s (%ss)", info.get("id"), int(duration))
    saved = _run_yt_dlp(
        [
            "-f",
            _FORMAT,
            "--merge-output-format",
            "mp4",
            "-o",
            str(dest / "source.%(ext)s"),
            "--no-playlist",
            "--restrict-filenames",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en.*,en",
            "--sub-format",
            "json3/vtt/best",
            "--socket-timeout",
            "20",
            "--retries",
            "2",
            url,
        ],
        timeout=max(180, int(duration) * 4),
    )
    if saved.returncode != 0:
        raise PipelineError(f"YouTube didn't allow this download. {_failure_text(saved)}")
    video = _find_video(dest)
    words: list[Word] = []
    caption = _caption_file(dest)
    if caption is not None:
        try:
            words = words_from_file(caption)
        except PipelineError:
            logger.warning("Caption file %s could not be parsed", caption.name)
            words = []
    title = str(info.get("title") or "").strip()[:180]
    return DownloadResult(
        video_path=str(video),
        title=title,
        duration=duration,
        heatmap=_load_heatmap(info),
        words=words,
    )
