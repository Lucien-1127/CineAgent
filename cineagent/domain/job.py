"""GenerationJob, QAReport — durable async job + QA result models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import JobState, OperationKind, ProjectStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GenerationJob(BaseModel):
    """A single remote generation attempt. Durable: remote_job_id is mandatory."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    project_id: str = ""
    scene_id: str = ""
    shot_id: str = ""
    provider: str = ""
    model: str = ""
    operation: OperationKind = OperationKind.VIDEO
    remote_job_id: Optional[str] = None  # survives crash; enables webhook/poll resume
    state: JobState = JobState.PENDING
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = Field(default=0, ge=0)
    input_asset_ids: List[str] = Field(default_factory=list)
    output_asset_ids: List[str] = Field(default_factory=list)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    actual_cost: float = Field(default=0.0, ge=0.0)
    error: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class QAReport(BaseModel):
    """QA output (technical + semantic/visual) for a shot."""

    model_config = ConfigDict(extra="forbid")

    shot_id: str
    project_id: str = ""
    stage: str = "technical"  # or "visual"
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    decision: str = "pending"  # pass / fail / repair
    problems: List[str] = Field(default_factory=list)
    severities: List[str] = Field(default_factory=list)  # per-problem severity
    repair_instructions: str = ""
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def passed(self) -> bool:
        return self.decision == "pass" or self.score >= self.threshold


__all__ = ["GenerationJob", "QAReport", "ProjectStatus"]
