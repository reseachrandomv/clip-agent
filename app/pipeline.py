"""One job: download, transcribe, pick moments, render clips."""

from __future__ import annotations

import logging

from app.config import Settings
from app.download import DownloadError, download_youtube
from app.llm import select_with_llm
from app.moments import select_moments
from app.render import RenderError, probe, render_clip
from app.subs import write_ass
from app.transcribe import TranscribeError, transcribe
from app.transcript import parse_vtt

logger = logging.getLogger(__name__)


class ClipError(RuntimeError):
    """A failure we can show to the person waiting on the job."""


def process_job(job_id: str, store, settings: Settings) -> None:
    job = store.get(job_id)
    work = store.workdir(job_id)
    try:
        if job["kind"] == "youtube":
            store.update(
                job_id,
                status="running",
                stage="download",
                message="Downloading the video",
                progress=8,
            )
            try:
                download = download_youtube(job["url"], work)
            except DownloadError as exc:
                raise ClipError(str(exc)) from exc
            source = download.path
            title = download.title
            vtt_text = download.vtt_text
            heatmap = download.heatmap
        else:
            store.update(
                job_id,
                status="running",
                stage="download",
                message="Checking the upload",
                progress=8,
            )
            source = work / "source.mp4"
            if not source.exists():
                raise ClipError("The upload never arrived.")
            title = job.get("filename") or "Upload"
            vtt_path = work / "captions.vtt"
            vtt_text = vtt_path.read_text(encoding="utf-8") if vtt_path.exists() else None
            heatmap = []

        info = probe(source)
        if not info.has_video:
            raise ClipError("That file does not look like a video.")
        duration = info.duration
        if duration <= 0.5:
            raise ClipError("That video is too short to clip.")
        if duration > settings.max_duration_sec:
            raise ClipError(
                f"This video is {int(duration)}s long. "
                f"Clip Agent stops at {settings.max_duration_sec}s so a small host can finish."
            )
        store.update(job_id, title=title, duration=round(duration, 3))

        if vtt_text and vtt_text.strip():
            store.update(
                job_id,
                stage="transcribe",
                message="Reading YouTube captions",
                progress=34,
            )
            segments = parse_vtt(vtt_text)
            transcript_source = "captions"
        else:
            store.update(
                job_id,
                stage="transcribe",
                message="No captions found. Transcribing locally",
                progress=34,
            )
            try:
                segments = transcribe(source, settings.whisper_model)
            except TranscribeError as exc:
                logger.exception("transcription failed")
                raise ClipError(str(exc)) from exc
            transcript_source = "whisper"
        if not segments:
            raise ClipError("No speech found to caption.")

        store.update(
            job_id,
            stage="pick",
            message="Picking the strongest moments",
            progress=56,
        )
        moments = None
        if settings.openai_api_key:
            store.update(job_id, message="Scoring moments with the language model", progress=58)
            moments = select_with_llm(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_model,
                duration=duration,
                segments=segments,
                heatmap=heatmap,
            )
        if not moments:
            moments = select_moments(duration, segments, heatmap)
        if not moments:
            raise ClipError("No clipable moments found in this video.")

        clips = []
        total = len(moments)
        for index, moment in enumerate(moments):
            store.update(
                job_id,
                stage="render",
                message=f"Rendering clip {index + 1} of {total}",
                progress=62 + int(32 * index / total),
            )
            video_path = work / f"clip-{index}.mp4"
            thumb_path = work / f"clip-{index}.jpg"
            ass_path = work / f"clip-{index}.ass"
            write_ass(
                ass_path,
                segments=segments,
                hook=moment.hook,
                clip_start=moment.start,
                clip_end=moment.end,
            )
            try:
                render_clip(
                    source,
                    moment.start,
                    moment.end,
                    ass_path,
                    video_path,
                    thumb_path,
                    preset=settings.render_preset,
                )
            except RenderError as exc:
                raise ClipError(f"Rendering clip {index + 1} failed. {exc}") from exc
            clips.append(
                {
                    "index": index,
                    "start": round(moment.start, 3),
                    "end": round(moment.end, 3),
                    "description": moment.description,
                    "hook": moment.hook,
                    "caption": moment.caption,
                    "video_path": str(video_path),
                    "thumb_path": str(thumb_path),
                    "size_bytes": video_path.stat().st_size,
                    "signals": list(moment.signals),
                }
            )

        store.update(
            job_id,
            status="done",
            stage="done",
            message=f"{len(clips)} clips ready",
            progress=100,
            clips=clips,
            transcript_source=transcript_source,
            error=None,
        )
    except ClipError as exc:
        store.update(
            job_id,
            status="error",
            stage="error",
            message=str(exc),
            error=str(exc),
            progress=100,
        )
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        message = "Something went wrong while making the clips."
        detail = str(exc).strip()
        if detail and len(detail) < 240:
            message = detail
        store.update(
            job_id,
            status="error",
            stage="error",
            message=message,
            error=message,
            progress=100,
        )
