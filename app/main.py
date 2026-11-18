"""HTTP API and the single-page UI."""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import Settings
from app.store import JobStore
from app.worker import Worker
from app.youtube import is_youtube_url

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
_CLIP_NAME = re.compile(r"clip-\d+\.(mp4|jpg)\Z")


class JobCreate(BaseModel):
    url: str = Field(min_length=12, max_length=500)


def _present(job: dict) -> dict:
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
                "video_url": f"/api/jobs/{job['id']}/clips/{index}/video",
                "thumbnail_url": f"/api/jobs/{job['id']}/clips/{index}/thumbnail",
            }
        )
    return {
        "id": job["id"],
        "url": job["url"],
        "title": job.get("title") or "",
        "duration": job.get("duration"),
        "status": job["status"],
        "stage": job.get("stage") or "",
        "detail": job.get("detail") or "",
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "clips": clips,
    }


def _clip_path(store: JobStore, job_id: str, index: int, kind: str) -> Path:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No job with that id.")
    clip = next((item for item in job.get("clips") or [] if item.get("index") == index), None)
    if clip is None:
        raise HTTPException(status_code=404, detail="That clip is not ready.")
    name = clip["video"] if kind == "video" else clip["thumbnail"]
    if not isinstance(name, str) or not _CLIP_NAME.fullmatch(name):
        raise HTTPException(status_code=404, detail="That clip is not ready.")
    folder = store.job_dir(job_id).resolve()
    path = (folder / name).resolve()
    if folder not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="That file is missing.")
    return path


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = JobStore(settings.data_dir)
    worker = Worker(store, settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker.start()
        try:
            yield
        finally:
            worker.stop()

    app = FastAPI(title="Clip Agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.worker = worker

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/jobs", status_code=202)
    def create_job(body: JobCreate) -> dict:
        url = body.url.strip()
        if not is_youtube_url(url):
            raise HTTPException(
                status_code=400,
                detail="Paste a YouTube video link, like https://www.youtube.com/watch?v=…",
            )
        job = store.create(url)
        worker.submit(job["id"])
        return _present(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="No job with that id.")
        return _present(job)

    @app.get("/api/jobs/{job_id}/clips/{index}/video")
    def clip_video(job_id: str, index: int):
        path = _clip_path(store, job_id, index, "video")
        return FileResponse(
            path,
            media_type="video/mp4",
            filename=path.name,
            content_disposition_type="inline",
        )

    @app.get("/api/jobs/{job_id}/clips/{index}/thumbnail")
    def clip_thumbnail(job_id: str, index: int):
        path = _clip_path(store, job_id, index, "thumbnail")
        return FileResponse(
            path,
            media_type="image/jpeg",
            filename=path.name,
            content_disposition_type="inline",
        )

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = app.state.settings
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    _ = settings


if __name__ == "__main__":
    main()
