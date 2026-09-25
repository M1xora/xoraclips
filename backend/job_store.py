"""
Background jobs kept in memory by ID (raw downloads, #64). A job is
forgotten an hour after it finishes, so the dicts no longer grow for as long
as the server runs; one that never finishes (a stuck download) is forgotten
after six hours. The background task holds its own reference to the job, so
writing to a forgotten job is harmless.
"""
import time
import uuid
from typing import Callable, Dict, Optional

JOB_TTL_SECONDS = 3600
JOB_MAX_AGE_SECONDS = 6 * 3600


def new_job_id() -> str:
    """A random ID nobody can guess (the old 8 characters could be tried)."""
    return uuid.uuid4().hex


class JobStore(dict):
    """Jobs by ID; `finish()` starts a job's hour, `lookup()` and `add()`
    forget the jobs whose hour (or six hours since `add()`) is over."""

    def __init__(self, ttl: float = JOB_TTL_SECONDS, max_age: float = JOB_MAX_AGE_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self.ttl = ttl
        self.max_age = max_age
        self.clock = clock
        self._added_at: Dict[str, float] = {}
        self._finished_at: Dict[str, float] = {}

    def add(self, job_id: str, job: dict) -> dict:
        self.forget_expired()
        self[job_id] = job
        self._added_at[job_id] = self.clock()
        return job

    def finish(self, job_id: str) -> None:
        if job_id in self:
            self._finished_at[job_id] = self.clock()

    def lookup(self, job_id: str) -> Optional[dict]:
        self.forget_expired()
        return self.get(job_id)

    def forget_expired(self) -> None:
        now = self.clock()
        expired = [job_id for job_id, finished in self._finished_at.items() if now - finished >= self.ttl]
        expired += [job_id for job_id, added in self._added_at.items() if now - added >= self.max_age]
        for job_id in expired:
            self._finished_at.pop(job_id, None)
            self._added_at.pop(job_id, None)
            self.pop(job_id, None)
