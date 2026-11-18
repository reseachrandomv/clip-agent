"""A single background worker, so a long video never holds an HTTP request open."""

from __future__ import annotations

import logging
import queue
import threading

from app.config import Settings
from app.store import JobStore

logger = logging.getLogger(__name__)

_ACTIVE = {"downloading", "transcribing", "picking", "rendering"}


class Worker:
    def __init__(self, store: JobStore, settings: Settings):
        self.store = store
        self.settings = settings
        self._queue: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        for job in self.store.all():
            if job["status"] == "queued":
                self._queue.put(job["id"])
            elif job["status"] in _ACTIVE:
                self.store.update(
                    job["id"],
                    status="error",
                    stage=job.get("stage") or "",
                    error="The server restarted while this job was running. Submit the link again.",
                    detail="Stopped",
                )
        self._thread = threading.Thread(target=self._loop, name="clip-agent", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def submit(self, job_id: str) -> None:
        self._queue.put(job_id)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.4)
            except queue.Empty:
                continue
            try:
                self._execute(job_id)
            finally:
                self._queue.task_done()

    def _execute(self, job_id: str) -> None:
        # Imported here so tests can patch app.pipeline.run_job before a job starts.
        from app.pipeline import run_job

        try:
            run_job(job_id, self.store, self.settings)
        except Exception:
            logger.exception("Job %s crashed", job_id)
            try:
                self.store.update(
                    job_id,
                    status="error",
                    error="Something went wrong while making the clips.",
                    detail="Failed",
                )
            except Exception:
                logger.exception("Could not record the failure for %s", job_id)
