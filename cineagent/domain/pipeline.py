"""Durable pipeline state and per-segment records for resume-safe long video.

Each segment keeps its inputs, provider/model, remote task id, output URL and
status. On resume, completed segments are never re-generated; a segment with a
remote job id is first queried (never blindly re-submitted).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SegmentState(BaseModel):
    """Full durable record of one generation segment."""

    model_config = ConfigDict(extra="forbid")

    segment_id: int
    time_start: float = 0.0
    time_end: float = 0.0
    duration_seconds: float = 0.0
    generation_duration_seconds: Optional[int] = None
    provider: str = ""
    model: str = ""
    status: str = "pending"  # pending/submitted/generating/succeeded/failed
    retry_count: int = Field(default=0, ge=0)
    remote_job_id: Optional[str] = None
    idempotency_key: str = ""
    start_frame_source: Optional[str] = None
    end_frame_source: Optional[str] = None
    previous_segment_id: Optional[int] = None
    audio_source: Optional[str] = None

    # inputs (provider-neutral)
    prompt: str = ""
    negative_prompt: str = ""
    image_url: Optional[str] = None
    start_frame_url: Optional[str] = None
    end_frame_url: Optional[str] = None
    reference_images: List[str] = Field(default_factory=list)
    reference_videos: List[str] = Field(default_factory=list)
    audio_url: Optional[str] = None
    native_audio: bool = False
    aspect_ratio: str = "9:16"
    resolution: str = "720p"

    # consistency bibles (kept per segment so every re-run is reproducible)
    character_bible: str = ""
    visual_style_bible: str = ""
    continuity_rules: List[str] = Field(default_factory=list)
    negative_prompt_rules: List[str] = Field(default_factory=list)
    camera_rules: List[str] = Field(default_factory=list)
    audio_rules: List[str] = Field(default_factory=list)

    # outputs
    output_url: Optional[str] = None
    local_path: Optional[str] = None
    last_frame_url: Optional[str] = None
    error: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        return (self.status == "succeeded" and bool(self.local_path)
                and Path(self.local_path).is_file()
                and Path(self.local_path).stat().st_size > 0)


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_retries_per_segment: int = Field(default=3, ge=0)
    max_total_duration_seconds: float = Field(default=60.0, gt=0)


class PipelineRunState(BaseModel):
    """Top-level run state; serializable to JSON for --resume."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    objective: str = ""
    locked_decisions: List[str] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    current_stage: str = "VIDEO_GENERATION"
    segments: Dict[str, SegmentState] = Field(default_factory=dict)
    completed: List[int] = Field(default_factory=list)
    failed: List[int] = Field(default_factory=list)
    pending: List[int] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    blockers: List[str] = Field(default_factory=list)
    last_error: Optional[str] = None
    plans: List[Dict[str, Any]] = Field(default_factory=list)
    planned_total_duration_seconds: Optional[float] = None
    seam_failures: List[str] = Field(default_factory=list)
    final_path: Optional[str] = None
    workdir: Optional[str] = None

    # ── helpers ───────────────────────────────────────────────────────
    def segment(self, segment_id: int) -> Optional[SegmentState]:
        return self.segments.get(str(segment_id))

    def ensure_segment(self, seg_id: int) -> SegmentState:
        key = str(seg_id)
        if key not in self.segments:
            self.segments[key] = SegmentState(segment_id=seg_id)
        return self.segments[key]

    def to_file(self, path: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Never truncate the last good checkpoint on an interrupted write.
        fd, tmp = tempfile.mkstemp(prefix=p.name + ".", dir=p.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(self.model_dump_json(indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, p)
            if os.name == "posix":
                directory = os.open(p.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return str(p)

    @classmethod
    def from_file(cls, path: str) -> "PipelineRunState":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        state = cls.model_validate(raw)
        if state.planned_total_duration_seconds is None and state.plans:
            state.planned_total_duration_seconds = max(float(p.get("time_end", 0.0)) for p in state.plans)
        return state


__all__ = ["SegmentState", "Budget", "PipelineRunState"]
