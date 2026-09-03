"""ShotSpec — the canonical, provider-independent generation unit."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    CameraAngle,
    CameraMotion,
    GenerationStrategy,
    QualityTier,
    ShotSize,
)


class ShotSpec(BaseModel):
    """One shot = the minimum independently generatable/QA-able/recoverable unit."""

    model_config = ConfigDict(extra="forbid")

    shot_id: str
    scene_id: str
    # Timeline (seconds), filled from the Audio Master Timeline.
    start_time: float = Field(default=0.0, ge=0.0)
    end_time: float = Field(default=0.0, ge=0.0)
    duration: float = Field(default=0.0, ge=0.0)
    narration_segment: str = ""
    visual_goal: str = ""
    subject: str = ""
    action: str = ""
    location: str = ""
    shot_size: ShotSize = ShotSize.MEDIUM
    camera_angle: CameraAngle = CameraAngle.EYE_LEVEL
    camera_motion: CameraMotion = CameraMotion.STATIC
    composition: str = ""
    lighting: str = ""
    continuity_in: str = ""
    continuity_out: str = ""
    first_frame_ref: Optional[str] = None
    last_frame_ref: Optional[str] = None
    reference_images: List[str] = Field(default_factory=list)
    reference_video: Optional[str] = None
    generation_strategy: GenerationStrategy = GenerationStrategy.GENERATED_IMAGE
    quality_tier: QualityTier = QualityTier.BALANCED
    provider_constraints: List[str] = Field(default_factory=list)


__all__ = ["ShotSpec"]
