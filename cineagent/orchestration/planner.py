"""Long-video segmentation planner.

Splits a total duration into per-model segments, each respecting the model's
max segment duration, with a configurable overlap for frame continuity. Every
segment is independently re-runnable and carries its frame/audio lineage.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SegmentPlan(BaseModel):
    """One generation segment of a longer film."""

    model_config = ConfigDict(extra="forbid")

    segment_id: int
    time_start: float = Field(ge=0.0)
    time_end: float = Field(ge=0.0)
    duration_seconds: float = Field(ge=0.0)
    provider: str
    model: str
    start_frame_source: Optional[str] = None    # keyframe | previous_last_frame | image_url
    end_frame_source: Optional[str] = None
    previous_segment_id: Optional[int] = None
    audio_source: Optional[str] = None
    status: str = "pending"
    retry_count: int = Field(default=0, ge=0)


def plan_segments(
    total_duration: float,
    max_segment_duration: float,
    overlap_seconds: float = 0.2,
    provider: str = "kling",
    model: str = "",
) -> List[SegmentPlan]:
    """Split `total_duration` into segments no longer than `max_segment_duration`.

    Consecutive segments overlap by `overlap_seconds` (the next segment's
    timeline start is pulled back), so the tail of segment *i* and the head of
    segment *i+1* cover the same film time — the stitching layer trims the
    duplicate. The first segment's start frame is a keyframe; every later
    segment sources its start frame from the previous segment's last frame.
    """
    if total_duration <= 0:
        raise ValueError("total_duration must be positive")
    if max_segment_duration <= 0:
        raise ValueError("max_segment_duration must be positive")
    if overlap_seconds < 0 or overlap_seconds >= max_segment_duration:
        raise ValueError(
            f"overlap_seconds must be in [0, {max_segment_duration})"
        )

    plans: List[SegmentPlan] = []
    cursor = 0.0
    segment_id = 0
    while cursor < total_duration - 1e-9:
        start = cursor
        dur = min(max_segment_duration, total_duration - start)
        end = start + dur
        previous = segment_id - 1 if segment_id > 0 else None
        plans.append(SegmentPlan(
            segment_id=segment_id,
            time_start=round(start, 3),
            time_end=round(end, 3),
            duration_seconds=round(dur, 3),
            provider=provider,
            model=model,
            start_frame_source="keyframe" if segment_id == 0 else "previous_last_frame",
            previous_segment_id=previous,
        ))
        if end >= total_duration - 1e-9:
            break
        cursor = end - overlap_seconds
        segment_id += 1
    return plans


__all__ = ["SegmentPlan", "plan_segments"]
