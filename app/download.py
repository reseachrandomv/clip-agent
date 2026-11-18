"""Download a YouTube video, its captions, and the most-replayed heatmap."""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.moments import HeatPoint

_VIDEO_ID = re.compile(r"[\w-]{6,}")
_YOUTUBE_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
}
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov"}
_FORMAT = (
    "bestvideo[height<=1080][height>=720][ext=mp4]+bestaudio[ext=m4a]/"
    "bestvideo[height<=1080][height>=720]+bestaudio/"
    "best[height<=1080][ext=mp4]/"
    "best[height<=1080]/best"
)


class DownloadError(RuntimeError):
    pass


@dataclass
class Download:
    path: Path
    title: str
    duration: float
    heatmap: list[HeatPoint]
    vtt_text: str | None


def validate_youtube_url(url: str) -> str:
    """Accept a single YouTube video URL and reject anything else (including other hosts)."""
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Paste a YouTube link (youtube.com or youtu.be).")
    host = parsed.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
        if not _VIDEO_ID.fullmatch(video_id):
            raise ValueError("Paste a YouTube link (youtube.com or youtu.be).")
        return cleaned
    if host not in _YOUTUBE_HOSTS:
        raise ValueError("Paste a YouTube link (youtube.com or youtu.be).")
    if parsed.path == "/watch":
        video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        if _VIDEO_ID.fullmatch(video_id):
            return cleaned
    match = re.fullmatch(r"/(shorts|embed|live)/([\w-]{6,})", parsed.path)
    if match:
        return cleaned
    raise ValueError("Paste a YouTube link (youtube.com or youtu.be).")


def heatmap_from_info(info: dict) -> list[HeatPoint]:
    points: list[HeatPoint] = []
    for item in info.get("heatmap") or []:
        if not isinstance(item, dict):
            continue
        try:
            points.append(
                HeatPoint(
                    start=float(item["start_time"]),
                    end=float(item["end_time"]),
                    value=float(item["value"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return points


def _find_video(dest: Path) -> Path:
    videos = [
        path
        for path in dest.glob("source.*")
        if path.suffix.lower() in _VIDEO_SUFFIXES and path.is_file()
    ]
    if not videos:
        raise DownloadError("yt-dlp finished without a video file.")
    mp4s = [path for path in videos if path.suffix.lower() == ".mp4"]
    return mp4s[0] if mp4s else videos[0]


def _read_vtt(dest: Path) -> str | None:
    files = sorted(path for path in dest.glob("*.vtt") if path.is_file())
    if not files:
        return None
    english = [path for path in files if ".en" in path.name.lower()]
    chosen = english[0] if english else files[0]
    return chosen.read_text(encoding="utf-8", errors="replace")


def _friendly(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if any(token in lowered for token in ("sign in", "bot", "confirm you’re not a bot", "confirm you're not a bot")):
        return (
            "YouTube blocked this download (it often does that from cloud servers). "
            "Upload the video file instead, or try again from a home connection."
        )
    if "private" in lowered or "unavailable" in lowered or "removed" in lowered:
        return "That YouTube video is unavailable. It may be private, deleted, or region-locked."
    if "live event" in lowered or "is live" in lowered:
        return "Live streams can't be clipped. Wait until the video is published."
    if len(text) > 280:
        text = text[:280].rsplit(" ", 1)[0] + "…"
    return text or "The YouTube download failed."


def _download_blocking(url: str, dest: Path) -> Download:
    import yt_dlp

    options = {
        "format": _FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(dest / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 20,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitlesformat": "vtt",
        "subtitleslangs": ["en-orig", "en", "en-US", "en-GB", "en.*"],
        "skip_unavailable_fragments": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise DownloadError(_friendly(exc)) from exc
    if not isinstance(info, dict):
        raise DownloadError("yt-dlp did not return video info.")
    if info.get("is_live"):
        raise DownloadError("Live streams can't be clipped. Wait until the video is published.")
    return Download(
        path=_find_video(dest),
        title=str(info.get("title") or "YouTube video"),
        duration=float(info.get("duration") or 0.0),
        heatmap=heatmap_from_info(info),
        vtt_text=_read_vtt(dest),
    )


def download_youtube(url: str, dest: Path, timeout: float | None = None) -> Download:
    """Download one video. A stuck extractor cannot hold the job queue forever."""
    validate_youtube_url(url)
    dest.mkdir(parents=True, exist_ok=True)
    if timeout is None:
        timeout = float(os.environ.get("DOWNLOAD_TIMEOUT_SEC", "300"))
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = _download_blocking(url, dest)
        except Exception as exc:
            box["error"] = exc

    worker = threading.Thread(target=run, name="yt-dlp", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise DownloadError(
            "The YouTube download took too long and was stopped. "
            "Upload the video file instead if this server is blocked."
        )
    if "error" in box:
        raise box["error"]
    return box["result"]
