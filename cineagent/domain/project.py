"""VideoProject — top-level canonical project model."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import Language, Platform, ProjectStatus, QualityMode


class VideoProject(BaseModel):
    """The top-level container for one video production."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(description="Stable project identifier (UUID or slug)")
    topic: str
    objective: str = ""
    audience: str = ""
    platform: Platform = Platform.SHORTS
    language: Language = Language.ZH_TW
    target_duration: float = Field(default=30.0, gt=0)
    aspect_ratio: str = Field(default="9:16")
    quality_mode: QualityMode = QualityMode.AUTO
    budget_limit: Optional[float] = Field(
        default=None, ge=0, description="Max spend in USD; None = unlimited"
    )
    status: ProjectStatus = ProjectStatus.DRAFTING
