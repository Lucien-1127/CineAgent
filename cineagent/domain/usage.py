"""Cost ledger usage event — every billable API call is recorded here."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from .enums import OperationKind


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UsageEvent(BaseModel):
    """One row per billable operation. Enables per-project / per-stage cost ledgers."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    project_id: str = ""
    scene_id: str = ""
    shot_id: str = ""
    provider: str = ""
    model: str = ""
    operation: OperationKind = OperationKind.VIDEO
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    image_count: int = Field(default=0, ge=0)
    video_seconds: float = Field(default=0.0, ge=0.0)
    audio_seconds: float = Field(default=0.0, ge=0.0)
    retry: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    actual_cost: float = Field(default=0.0, ge=0.0)
    status: str = "ok"  # ok / failed / billed_failed
    created_at: datetime = Field(default_factory=_utcnow)
