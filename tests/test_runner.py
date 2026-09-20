"""Runner: success, resume-skip, retry cap, blocker stop."""
import asyncio
import json
from pathlib import Path

from cineagent.domain import Budget, PipelineRunState
from cineagent.orchestration import VideoPipelineRunner, plan_segments
from cineagent.providers.base import AuthError, RateLimitError
from conftest import FakeVideoProvider
import pytest


def _run(coro):
    return asyncio.run(coro)


def _state():
    return PipelineRunState(run_id="r", objective="test",
                            provider="fake-video", model="fake-model")


def _plans(total=10, max_dur=5):
    plans = plan_segments(total, max_dur, overlap_seconds=0.0,
                         provider="fake-video", model="fake-model")
    # Lifecycle unit tests use placeholder videos, not real frame chaining.
    for plan in plans:
        plan.start_frame_source = "keyframe"
    return plans


def test_run_all_segments_succeed(tmp_path):
    prov = FakeVideoProvider(str(tmp_path))
    state = _state()
    runner = VideoPipelineRunner(prov, str(tmp_path / "out"), poll_interval=0.0)
    state = _run(runner.run(state, _plans(), stitch=False))
    assert state.completed == [0, 1]
    assert state.failed == []
    assert prov.create_calls == [0, 1]


def test_resume_skips_completed(tmp_path):
    prov = FakeVideoProvider(str(tmp_path))
    state = _state()
    s0 = state.ensure_segment(0)
    s0.status = "succeeded"
    s0.output_url = "http://x/0.mp4"
    s0.local_path = str(tmp_path / "0.mp4")
    Path(s0.local_path).write_bytes(b"video-placeholder")

    runner = VideoPipelineRunner(prov, str(tmp_path / "out"), poll_interval=0.0)
    state = _run(runner.run(state, _plans(), stitch=False))
    assert prov.create_calls == [1]  # only segment 1 was submitted
    assert state.completed == [0, 1]


def test_resume_restores_budget_from_saved_plan(tmp_path):
    prov = FakeVideoProvider(str(tmp_path))
    plans = _plans(total=70, max_dur=35)
    path = tmp_path / "state.json"
    state = _state()
    state.plans = [plan.model_dump() for plan in plans]
    path.write_text(json.dumps({
        **state.model_dump(),
        "budget": {"max_retries_per_segment": 3, "max_total_duration_seconds": 60.0},
    }))
    state = PipelineRunState.from_file(str(path))

    runner = VideoPipelineRunner(prov, str(tmp_path / "out"), poll_interval=0.0)
    state = _run(runner.run(state, plans, stitch=False))

    assert state.planned_total_duration_seconds == 70
    assert state.budget.max_total_duration_seconds == 60
    assert prov.create_calls == [0, 1]
    assert state.completed == [0, 1]


def test_stitch_rejects_non_uniform_overlap(tmp_path):
    runner = VideoPipelineRunner(FakeVideoProvider(str(tmp_path)), str(tmp_path / "out"), poll_interval=0.0)
    segments = [
        state for state in (
            PipelineRunState(run_id="s0").ensure_segment(0),
            PipelineRunState(run_id="s1").ensure_segment(1),
            PipelineRunState(run_id="s2").ensure_segment(2),
        )
    ]
    for seg, start, end in zip(segments, (0.0, 4.5, 9.0), (5.0, 9.8, 14.8)):
        seg.time_start = start
        seg.time_end = end
        seg.duration_seconds = end - start
        seg.local_path = str(tmp_path / f"{seg.segment_id}.mp4")
    with pytest.raises(ValueError, match="uniform overlap"):
        _run(runner._stitch(segments, "9:16", 30))


def test_retry_cap_exhausted(tmp_path):
    class RateLimitProvider(FakeVideoProvider):
        async def create_task(self, request):
            raise RateLimitError("429")

    prov = RateLimitProvider(str(tmp_path))
    state = _state()
    state.budget = Budget(max_retries_per_segment=2)
    runner = VideoPipelineRunner(prov, str(tmp_path / "out"), poll_interval=0.0)
    state = _run(runner.run(state, _plans(total=5, max_dur=5), stitch=False))

    seg = state.segment(0)
    assert seg.status == "failed"
    assert seg.retry_count == 2  # exhausted the budget
    assert state.failed == [0]


def test_blocker_stops_run(tmp_path):
    class AuthProvider(FakeVideoProvider):
        async def create_task(self, request):
            raise AuthError("401 bad key")

    prov = AuthProvider(str(tmp_path))
    state = _state()
    runner = VideoPipelineRunner(prov, str(tmp_path / "out"), poll_interval=0.0)
    state = _run(runner.run(state, _plans(), stitch=False))

    assert state.blockers
    assert state.current_stage == "BLOCKED"
    assert state.completed == []
