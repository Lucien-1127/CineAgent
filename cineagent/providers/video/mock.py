"""Durable, idempotent in-memory VideoProvider for tests/offline.

Emulates an async remote video job: submit() returns a stable remote_job_id
derived from idempotency_key (so re-submitting never bills twice); poll()
advances a simple submitted->succeeded state machine.
"""
from __future__ import annotations

import hashlib
from typing import Dict

from .base import VideoJobRef, VideoProvider, VideoRequest, VideoResult


class MockVideoProvider(VideoProvider):
    name = "mock-video"
    model = "mock-video-model"
    poll_interval_s = 0.0
    supports_webhook = False

    def __init__(self) -> None:
        self._jobs: Dict[str, str] = {}  # remote_job_id -> state
        self._results: Dict[str, str] = {}

    def remote_id(self, req: VideoRequest) -> str:
        key = req.idempotency_key or f"{req.prompt}|{req.duration}|{req.candidate_index}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    async def submit(self, req: VideoRequest) -> VideoJobRef:
        rid = self.remote_id(req)
        if rid not in self._jobs:
            self._jobs[rid] = "submitted"  # first submit only => no double billing
        return VideoJobRef(provider=self.name, model=self.model, remote_job_id=rid)

    def complete(self, remote_job_id: str, uri: str = "file://gen.mp4") -> None:
        """Test hook: force a job to succeed (simulates async completion)."""
        self._jobs[remote_job_id] = "succeeded"
        self._results[remote_job_id] = uri

    async def poll(self, remote_job_id: str) -> VideoResult:
        state = self._jobs.get(remote_job_id, "failed")
        if state == "succeeded":
            return VideoResult(
                uri=self._results.get(remote_job_id, ""), state="succeeded",
                remote_job_id=remote_job_id,
            )
        if state in ("submitted", "generating"):
            self._jobs[remote_job_id] = "generating"
            return VideoResult(state="generating", remote_job_id=remote_job_id)
        return VideoResult(state="failed", error="unknown job",
                           remote_job_id=remote_job_id)
