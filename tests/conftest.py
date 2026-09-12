"""Shared test helpers for the video pipeline."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from cineagent.providers.video.generation import GenerationProvider
from cineagent.providers.video.schemas import (
    VideoTask,
    VideoTaskState,
    VideoTaskStatus,
)


def make_video(path, duration: int = 2, color: str = "navy", size: str = "270x480") -> str:
    """Create a real, playable MP4 via ffmpeg (raises if ffmpeg is missing)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"color=c={color}:s={size}:d={duration}", "-pix_fmt", "yuv420p",
         "-c:v", "libx264", path],
        check=True,
    )
    return path


class FakeVideoProvider(GenerationProvider):
    """Deterministic offline provider: create -> immediate success on poll.

    ``create_calls`` records segment ids so resume/retry tests can assert on
    how many tasks were actually submitted. No ffmpeg needed (download copies
    a placeholder file); use for unit tests that don't stitch.
    """

    name = "fake-video"

    def __init__(self, workdir: str = "/tmp/cineagent-fake") -> None:
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.create_calls: list = []
        self.fail_next: bool = False

    async def create_task(self, request):
        self.create_calls.append(request.metadata.get("segment_id"))
        rid = f"job-{len(self.create_calls)}"
        return VideoTask(provider=self.name, model=request.model,
                         remote_job_id=rid, status=VideoTaskState.QUEUED)

    async def get_task(self, remote_job_id):
        if self.fail_next:
            self.fail_next = False
            return VideoTaskStatus(remote_job_id=remote_job_id,
                                   state=VideoTaskState.FAILED,
                                   error_message="boom")
        vid = self.workdir / f"{remote_job_id}.mp4"
        if not vid.exists():
            vid.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
        return VideoTaskStatus(remote_job_id=remote_job_id,
                               state=VideoTaskState.SUCCEEDED,
                               video_url=str(vid))

    async def download_result(self, task, output_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(task.video_url, output_path)
        return output_path
