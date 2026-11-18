"""A small on-disk queue. The HTTP request returns before ffmpeg does."""

from __future__ import annotations

import copy
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import Settings

_JOB_ID = re.compile(r"[a-f0-9]{32}")


class JobStore:
    def __init__(self, settings: Settings, runner) -> None:
        self.settings = settings
        self._runner = runner
        self.jobs_dir = settings.data_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._executor = ThreadPoolExecutor(max_workers=settings.workers, thread_name_prefix="clip")
        self._load()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def workdir(self, job_id: str) -> Path:
        self._check_id(job_id)
        path = self.jobs_dir / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get(self, job_id: str) -> dict:
        self._check_id(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return copy.deepcopy(job)

    def create_youtube(self, url: str) -> dict:
        job = self._blank(kind="youtube", url=url)
        self._executor.submit(self._run, job["id"])
        return copy.deepcopy(job)

    def create_upload(self, filename: str) -> dict:
        safe_name = Path(filename or "upload.mp4").name or "upload.mp4"
        return self._blank(
            kind="upload",
            filename=safe_name,
            status="receiving",
            message="Receiving the upload",
        )

    def enqueue(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "queued"
            job["stage"] = "download"
            job["message"] = "Queued"
            self._write(job)
            snapshot = copy.deepcopy(job)
        self._executor.submit(self._run, job_id)
        return snapshot

    def update(self, job_id: str, **fields) -> dict:
        with self._lock:
            job = self._jobs[job_id]
            job.update(fields)
            self._write(job)
            return copy.deepcopy(job)

    def _blank(self, **extra) -> dict:
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "kind": "youtube",
            "url": None,
            "filename": None,
            "status": "queued",
            "stage": "download",
            "message": "Queued",
            "progress": 0,
            "error": None,
            "title": None,
            "duration": None,
            "clips": [],
            "transcript_source": None,
            "created_at": time.time(),
        }
        job.update(extra)
        with self._lock:
            self.workdir(job_id)
            self._jobs[job_id] = job
            self._write(job)
            return copy.deepcopy(job)

    def _run(self, job_id: str) -> None:
        try:
            self._runner(job_id, self)
        except Exception as exc:
            self.update(
                job_id,
                status="error",
                stage="error",
                message=str(exc) or "The job failed.",
                error=str(exc) or "The job failed.",
                progress=100,
            )

    def _load(self) -> None:
        for path in self.jobs_dir.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(job, dict) or not _JOB_ID.fullmatch(str(job.get("id") or "")):
                continue
            if job.get("status") in {"queued", "running", "receiving"}:
                job["status"] = "error"
                job["stage"] = "error"
                job["error"] = "The server restarted before this job finished."
                job["message"] = job["error"]
                self._write(job)
            self._jobs[job["id"]] = job

    def _write(self, job: dict) -> None:
        path = self.jobs_dir / job["id"] / "job.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _check_id(job_id: str) -> None:
        if not _JOB_ID.fullmatch(job_id or ""):
            raise KeyError(job_id)
