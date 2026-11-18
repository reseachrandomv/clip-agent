"""Run one job from download through the vertical renders."""

from __future__ import annotations

import logging
from pathlib import Path

from app.captions import build_ass, cues_for_clip
from app.config import Settings
from app.llm import choose_moments
from app.models import PipelineError
from app.moments import rank_moments
from app.render import render_clip
from app.store import JobStore
from app.transcript import transcribe_audio
from app.youtube import download_video

logger = logging.getLogger(__name__)


def run_job(job_id: str, store: JobStore, settings: Settings) -> None:
    job = store.get(job_id)
    if job is None:
        return
    folder = store.job_dir(job_id)
    try:
        store.update(job_id, status="downloading", stage="download", detail="Downloading the video…", error=None)
        downloaded = download_video(job["url"], folder, settings)
        store.update(
            job_id,
            status="transcribing",
            stage="transcribe",
            detail="Reading captions…",
            title=downloaded.title,
            duration=downloaded.duration,
        )
        words = list(downloaded.words)
        if not words:
            store.update(job_id, detail="No captions on YouTube. Transcribing the audio…")
            words = transcribe_audio(Path(downloaded.video_path), settings)
        if not words:
            raise PipelineError("No speech turned up in the captions or the audio, so there is nothing to caption.")

        store.update(job_id, status="picking", stage="pick", detail="Picking the strongest moments…")
        ranked = rank_moments(words, downloaded.heatmap, downloaded.duration, title=downloaded.title)
        moments = choose_moments(ranked, downloaded.duration, settings)
        if not moments:
            raise PipelineError("No clip could be cut from this video.")

        store.update(job_id, status="rendering", stage="render", detail=f"Rendering {len(moments)} clips…")
        clips = []
        source = Path(downloaded.video_path)
        for index, moment in enumerate(moments):
            store.update(job_id, detail=f"Rendering clip {index + 1} of {len(moments)}…")
            ass_path = folder / f"clip-{index + 1}.ass"
            video_name = f"clip-{index + 1}.mp4"
            thumb_name = f"clip-{index + 1}.jpg"
            cues = cues_for_clip(words, moment.start, moment.end)
            ass_path.write_text(build_ass(cues, moment.hook), encoding="utf-8")
            render_clip(source, moment.start, moment.end, ass_path, folder / video_name, folder / thumb_name)
            clips.append(
                {
                    "index": index,
                    "start": moment.start,
                    "end": moment.end,
                    "description": moment.description,
                    "hook": moment.hook,
                    "caption": moment.caption,
                    "video": video_name,
                    "thumbnail": thumb_name,
                }
            )
        try:
            source.unlink()
        except OSError:
            logger.warning("Could not remove the source video for %s", job_id)
        store.update(job_id, status="done", stage="render", detail="Ready", clips=clips, error=None)
    except PipelineError as exc:
        logger.info("Job %s failed: %s", job_id, exc)
        store.update(job_id, status="error", error=str(exc), detail=str(exc)[:240])
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        store.update(
            job_id,
            status="error",
            error="Something went wrong while making the clips.",
            detail=str(exc)[:240],
        )
