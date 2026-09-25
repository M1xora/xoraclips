"""
Background jobs (raw downloads, render batches) kept in memory by ID. A job
is forgotten an hour after it finishes, so the dicts no longer grow for as
long as the server runs (#64, #70). Running jobs are never forgotten: the
background task keeps writing to them.
"""
import time
import uuid
from typing import Callable, Dict, Optional

JOB_TTL_SECONDS = 3600


def new_job_id() -> str:
    """A random ID nobody can guess (the old 8 characters could be tried)."""
    return uuid.uuid4().hex


class JobStore(dict):
    """Jobs by ID; `finish()` starts a job's hour, `lookup()` and `add()`
    forget the jobs whose hour is over."""

    def __init__(self, ttl: float = JOB_TTL_SECONDS, clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self.ttl = ttl
        self.clock = clock
        self._finished_at: Dict[str, float] = {}

    def add(self, job_id: str, job: dict) -> dict:
        self.forget_expired()
        self[job_id] = job
        return job

    def finish(self, job_id: str) -> None:
        if job_id in self:
            self._finished_at[job_id] = self.clock()

    def lookup(self, job_id: str) -> Optional[dict]:
        self.forget_expired()
        return self.get(job_id)

    def forget_expired(self) -> None:
        now = self.clock()
        for job_id, finished in list(self._finished_at.items()):
            if now - finished >= self.ttl:
                self._finished_at.pop(job_id, None)
                self.pop(job_id, None)
