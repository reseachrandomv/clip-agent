"""Disk-backed job records. One folder per job, so a restart can still serve finished clips."""

from __future__ import annotations

import copy
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        for path in self.root.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            job_id = job.get("id")
            if isinstance(job_id, str):
                self._jobs[job_id] = job

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def create(self, url: str) -> dict:
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "url": url,
            "title": "",
            "duration": None,
            "status": "queued",
            "stage": "",
            "detail": "Queued",
            "error": None,
            "clips": [],
            "created_at": _now(),
        }
        with self._lock:
            self._jobs[job_id] = job
            self._write(job)
            return copy.deepcopy(job)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return copy.deepcopy(job) if job else None

    def all(self) -> list[dict]:
        with self._lock:
            return [copy.deepcopy(job) for job in self._jobs.values()]

    def update(self, job_id: str, **fields) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            job.update(fields)
            self._write(job)
            return copy.deepcopy(job)

    def _write(self, job: dict) -> None:
        folder = self.job_dir(job["id"])
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "job.json"
        temporary = folder / "job.json.tmp"
        temporary.write_text(json.dumps(job, indent=2), encoding="utf-8")
        temporary.replace(target)
