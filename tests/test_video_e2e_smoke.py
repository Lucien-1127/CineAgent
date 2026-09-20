"""Offline E2E smoke: plan -> mock generate -> ffmpeg stitch -> QA.

No real API. Uses a provider that writes real MP4s (via ffmpeg) and succeeds
immediately, so the full seam path is exercised without credentials.
"""
import asyncio
import shutil
from pathlib import Path

import pytest

from cineagent.domain import PipelineRunState
from cineagent.orchestration import VideoPipelineRunner, plan_segments
from cineagent.providers.video.schemas import (
    VideoTask,
    VideoTaskState,
    VideoTaskStatus,
)
from cineagent.qa import TechnicalQA
from conftest import make_video

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg required",
)


class AutoCompleteVideoProvider:
    """GenerationProvider that returns a real MP4 and succeeds on first poll."""

    name = "autocomplete-real"

    def __init__(self, workdir: str) -> None:
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._dur = {}

    async def create_task(self, request):
        rid = f"j{request.metadata.get('segment_id')}"
        self._dur[rid] = max(1, request.duration_seconds)
        return VideoTask(provider=self.name, model=request.model,
                         remote_job_id=rid, status=VideoTaskState.QUEUED)

    async def get_task(self, remote_job_id):
        vid = self.workdir / f"{remote_job_id}.mp4"
        if not vid.exists():
            make_video(str(vid), duration=max(1, int(self._dur.get(remote_job_id, 2))))
        return VideoTaskStatus(remote_job_id=remote_job_id,
                               state=VideoTaskState.SUCCEEDED,
                               video_url=str(vid),
                               duration_seconds=float(self._dur.get(remote_job_id, 2)))

    async def download_result(self, task, output_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(task.video_url, output_path)
        return Path(output_path)


def test_e2e_plan_generate_stitch_qa(tmp_path):
    prov = AutoCompleteVideoProvider(str(tmp_path / "gen"))
    plans = plan_segments(9, 5, overlap_seconds=0.2,
                          provider="autocomplete-real", model="m")
    assert len(plans) == 2

    state = PipelineRunState(
        run_id="e2e", objective="城市夜景動畫", provider="autocomplete-real", model="m",
        locked_decisions=["Agnes 全面棄用", "動畫只使用 Seedance 與 Kling"],
    )
    for p in plans:
        state.ensure_segment(p.segment_id).prompt = "城市夜景動畫"

    runner = VideoPipelineRunner(prov, str(tmp_path / "out"), poll_interval=0.0)
    state = asyncio.run(runner.run(state, plans, stitch=True, aspect="9:16"))

    assert state.completed == [0, 1]
    assert state.failed == []
    assert state.current_stage == "STITCHED"

    final = tmp_path / "out" / "final.mp4"
    assert final.exists()
    report = TechnicalQA().assess(str(final))
    assert report.passed
