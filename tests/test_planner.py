"""Segmentation planner: duration math, overlap, and lineage."""
import pytest

from cineagent.orchestration import plan_segments


def test_single_segment_when_under_max():
    plans = plan_segments(5, 10, provider="kling", model="kling-v3")
    assert len(plans) == 1
    assert plans[0].time_start == 0.0
    assert plans[0].time_end == 5.0
    assert plans[0].start_frame_source == "keyframe"
    assert plans[0].previous_segment_id is None


def test_split_with_overlap():
    plans = plan_segments(12, 5, overlap_seconds=0.2, provider="kling", model="kling-v3")
    assert len(plans) == 3
    # segment 1 starts before segment 0 ends (overlap)
    assert plans[1].time_start < plans[0].time_end
    assert round(plans[0].time_end - plans[1].time_start, 2) == 0.2
    # lineage
    assert plans[0].start_frame_source == "keyframe"
    assert plans[1].start_frame_source == "previous_last_frame"
    assert plans[1].previous_segment_id == 0
    assert plans[2].previous_segment_id == 1
    # coverage reaches total
    assert plans[-1].time_end == 12.0


def test_exact_multiple_no_remainder():
    plans = plan_segments(10, 5, overlap_seconds=0.0)
    assert len(plans) == 2
    assert plans[1].time_end == 10.0


def test_all_segments_within_max_duration():
    plans = plan_segments(33, 10, overlap_seconds=0.2)
    for p in plans:
        assert p.duration_seconds <= 10 + 1e-6


def test_invalid_total_duration():
    with pytest.raises(ValueError):
        plan_segments(0, 5)
    with pytest.raises(ValueError):
        plan_segments(-3, 5)


def test_invalid_max_duration():
    with pytest.raises(ValueError):
        plan_segments(10, 0)


def test_invalid_overlap():
    with pytest.raises(ValueError):
        plan_segments(10, 5, overlap_seconds=-1)
    with pytest.raises(ValueError):
        plan_segments(10, 5, overlap_seconds=5)
