"""Offline GenerationProvider mock for tests and E2E smoke.

Implements the create_task/get_task/download_result contract with no network.
``complete()`` is a test hook to simulate async success (mirrors the existing
MockVideoProvider lifecycle, but over the unified generation contract).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict

from .generation import GenerationProvider
from .schemas import (
    VideoGenerationRequest,
    VideoTask,
    VideoTaskState,
    VideoTaskStatus,
)


class MockGenerationProvider(GenerationProvider):
    name = "mock-generation"

    def __init__(self, out_dir: str = "/tmp/cineagent-mock-gen",
                 auto_succeed: bool = False) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.auto_succeed = auto_succeed
        self._state: Dict[str, str] = {}       # remote_job_id -> state
        self._urls: Dict[str, str] = {}        # remote_job_id -> video path

    def remote_id(self, request: VideoGenerationRequest) -> str:
        key = request.idempotency_key or (
            f"{request.prompt}|{request.duration_seconds}|{request.model}"
        )
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    async def create_task(self, request: VideoGenerationRequest) -> VideoTask:
        rid = self.remote_id(request)
        self._state.setdefault(rid, "submitted")  # idempotent: no double submit
        if self.auto_succeed:
            self._state[rid] = "succeeded"
            vid = self.out_dir / f"{rid}.mp4"
            if not vid.exists():
                self._make_video(vid, request.duration_seconds)
            self._urls[rid] = str(vid)
        return VideoTask(provider=self.name, model=request.model,
                         remote_job_id=rid, status=VideoTaskState.QUEUED)

    def _make_video(self, path: Path, duration: int) -> None:
        import shutil
        import subprocess
        if shutil.which("ffmpeg"):
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                 f"color=c=navy:s=270x480:d={max(1, int(duration))}",
                 "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)],
                check=True,
            )
        else:
            path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

    def complete(self, remote_job_id: str, video_path: str) -> None:
        """Test hook: force a job to succeed with a local video file."""
        self._state[remote_job_id] = "succeeded"
        self._urls[remote_job_id] = video_path

    async def get_task(self, remote_job_id: str) -> VideoTaskStatus:
        state = self._state.get(remote_job_id, "failed")
        if state == "succeeded":
            return VideoTaskStatus(
                remote_job_id=remote_job_id,
                state=VideoTaskState.SUCCEEDED,
                video_url=self._urls.get(remote_job_id),
            )
        if state in ("submitted", "generating"):
            self._state[remote_job_id] = "generating"
            return VideoTaskStatus(remote_job_id=remote_job_id,
                                   state=VideoTaskState.RUNNING)
        return VideoTaskStatus(remote_job_id=remote_job_id,
                               state=VideoTaskState.FAILED,
                               error_message="unknown job")

    async def download_result(self, task: VideoTaskStatus, output_path: Path) -> Path:
        src = task.video_url
        if not src or not Path(src).exists():
            raise IOError("mock video source missing")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(Path(src).read_bytes())
        return output_path


__all__ = ["MockGenerationProvider"]
