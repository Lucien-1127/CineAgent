"""Script-layer canonical models: CreativeBrief, Scene, ScriptPackage."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import Platform, ScriptStrategy


class CreativeBrief(BaseModel):
    """Direction set before writing. Provider-independent."""

    model_config = ConfigDict(extra="forbid")

    audience: str = ""
    core_message: str = ""
    emotional_goal: str = ""
    content_type: str = ""  # e.g. explainer, brand-story, tutorial
    references: List[str] = Field(default_factory=list)
    prohibited_elements: List[str] = Field(default_factory=list)
    cta_strategy: str = ""  # e.g. follow, subscribe, click_link


class Fact(BaseModel):
    """A single claim that should be verified for factual content."""

    model_config = ConfigDict(extra="forbid")

    statement: str
    source: str = ""
    verified: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Scene(BaseModel):
    """Story unit (NOT the generation unit). A Scene owns one or more Shots."""

    model_config = ConfigDict(extra="forbid")

    scene_id: str
    title: str = ""
    goal: str = ""
    story_beat: str = ""
    narration: str = ""
    emotion: str = ""
    # Ordering within the script timeline.
    index: int = 0
    # Filled during Audio Timeline phase (seconds).
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class ScriptPackage(BaseModel):
    """The validated output of the Script Engine."""

    model_config = ConfigDict(extra="forbid")

    hook: str = ""
    narration: str = ""  # full continuous narration text
    scenes: List[Scene] = Field(default_factory=list)
    facts: List[Fact] = Field(default_factory=list)
    cta: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    script_strategy: ScriptStrategy = ScriptStrategy.SHORT_VIRAL
    expected_duration: Optional[float] = Field(
        default=None, description="Estimated seconds (refined by Audio phase)"
    )
    platform: Platform = Platform.SHORTS
