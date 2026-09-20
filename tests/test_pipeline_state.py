"""Durable pipeline state: save/restore, completeness, resume data."""
from cineagent.domain import Budget, PipelineRunState, SegmentState


def test_roundtrip_file(tmp_path):
    state = PipelineRunState(
        run_id="r1", objective="obj", provider="kling", model="kling-v3",
        locked_decisions=["Agnes 全面棄用", "動畫只使用 Seedance 與 Kling"],
    )
    seg = state.ensure_segment(0)
    seg.status = "succeeded"
    seg.output_url = "http://x/v.mp4"
    seg.local_path = "/tmp/x.mp4"
    path = state.to_file(str(tmp_path / "state.json"))

    loaded = PipelineRunState.from_file(path)
    assert loaded.run_id == "r1"
    assert loaded.locked_decisions[0] == "Agnes 全面棄用"
    assert loaded.segment(0).is_complete
    assert loaded.segment(0).output_url == "http://x/v.mp4"


def test_is_complete_requires_output():
    s = SegmentState(segment_id=0, status="succeeded")
    assert not s.is_complete  # succeeded but no output URL/path yet
    s.output_url = "http://x/v.mp4"
    assert s.is_complete


def test_ensure_segment_idempotent():
    state = PipelineRunState(run_id="r", provider="kling")
    a = state.ensure_segment(0)
    b = state.ensure_segment(0)
    assert a is b
    assert len(state.segments) == 1


def test_budget_defaults():
    b = Budget()
    assert b.max_retries_per_segment == 3
    assert b.max_total_duration_seconds == 60.0
