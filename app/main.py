"""HTTP API and the single-page UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import Settings
from app.download import validate_youtube_url
from app.jobs import JobStore
from app.pipeline import process_job

logger = logging.getLogger(__name__)
STATIC = Path(__file__).resolve().parent.parent / "static"


class JobRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)


def public_job(job: dict) -> dict:
    clips = []
    for clip in job.get("clips") or []:
        index = clip["index"]
        clips.append(
            {
                "index": index,
                "start": clip["start"],
                "end": clip["end"],
                "description": clip["description"],
                "hook": clip["hook"],
                "caption": clip["caption"],
                "size_bytes": clip.get("size_bytes"),
                "video_url": f"/api/jobs/{job['id']}/clips/{index}/video",
                "thumb_url": f"/api/jobs/{job['id']}/clips/{index}/thumb",
            }
        )
    return {
        "id": job["id"],
        "status": job["status"],
        "stage": job["stage"],
        "message": job["message"],
        "progress": job["progress"],
        "error": job.get("error"),
        "title": job.get("title"),
        "duration": job.get("duration"),
        "clips": clips,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    def runner(job_id: str, store: JobStore) -> None:
        process_job(job_id, store, settings)

    store = JobStore(settings, runner)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        store.shutdown()

    app = FastAPI(title="Clip Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/api/jobs")
    def create_job(body: JobRequest) -> dict:
        try:
            url = validate_youtube_url(body.url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return public_job(store.create_youtube(url))

    @app.post("/api/jobs/upload")
    async def upload_job(
        file: UploadFile = File(...),
        captions: UploadFile | None = File(None),
    ) -> dict:
        job = store.create_upload(file.filename or "upload.mp4")
        work = store.workdir(job["id"])
        dest = work / "source.mp4"
        limit = settings.max_upload_mb * 1024 * 1024
        size = 0
        try:
            with dest.open("wb") as handle:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Files must be under {settings.max_upload_mb}MB.",
                        )
                    handle.write(chunk)
            if captions is not None:
                text = (await captions.read()).decode("utf-8", errors="replace")
                if text.strip():
                    (work / "captions.vtt").write_text(text, encoding="utf-8")
        except HTTPException:
            dest.unlink(missing_ok=True)
            store.update(
                job["id"],
                status="error",
                stage="error",
                message="That file is too large.",
                error="That file is too large.",
                progress=100,
            )
            raise
        if size == 0:
            store.update(
                job["id"],
                status="error",
                stage="error",
                message="That upload was empty.",
                error="That upload was empty.",
                progress=100,
            )
            raise HTTPException(status_code=400, detail="That upload was empty.")
        return public_job(store.enqueue(job["id"]))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        try:
            return public_job(store.get(job_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="No job with that id.") from None

    @app.get("/api/jobs/{job_id}/clips/{index}/video")
    def clip_video(job_id: str, index: int) -> FileResponse:
        return _clip_file(store, job_id, index, "video_path", "video/mp4", f"clip-{index + 1}.mp4")

    @app.get("/api/jobs/{job_id}/clips/{index}/thumb")
    def clip_thumb(job_id: str, index: int) -> FileResponse:
        return _clip_file(store, job_id, index, "thumb_path", "image/jpeg", f"clip-{index + 1}.jpg")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def _clip_file(store: JobStore, job_id: str, index: int, key: str, media_type: str, filename: str) -> FileResponse:
    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No job with that id.") from None
    matches = [clip for clip in job.get("clips") or [] if clip.get("index") == index]
    if not matches:
        raise HTTPException(status_code=404, detail="No clip with that index.")
    path = Path(matches[0][key])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That file is gone.")
    return FileResponse(path, media_type=media_type, filename=filename)


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


_configure_logging()
app = create_app()
