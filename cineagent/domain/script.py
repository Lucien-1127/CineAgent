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
    audience_problem: str = ""
    viewer_promise: str = ""
    novelty_angle: str = ""
    proof_points: List[str] = Field(default_factory=list)
    trend_context: List[str] = Field(default_factory=list)
    platform_native_style: str = ""
    originality_plan: str = ""
    primary_success_metric: str = "average_percentage_viewed"


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


class HookCandidate(BaseModel):
    """A single hook candidate + its score."""

    model_config = ConfigDict(extra="forbid")

    text: str
    hook_type: str = ""  # question / shocking / story / stat / cta
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    audience_relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    promise_clarity: float = Field(default=0.5, ge=0.0, le=1.0)
    curiosity: float = Field(default=0.5, ge=0.0, le=1.0)
    payoff_alignment: float = Field(default=0.5, ge=0.0, le=1.0)
    credibility: float = Field(default=0.5, ge=0.0, le=1.0)


class HookSet(BaseModel):
    """Generated hook candidates for scoring/picking."""

    model_config = ConfigDict(extra="forbid")

    candidates: List[HookCandidate] = Field(default_factory=list)


class CritiqueResult(BaseModel):
    """Output of the ScriptCritic."""

    model_config = ConfigDict(extra="forbid")

    passed: bool = False
    notes: List[str] = Field(default_factory=list)
    revision_guidance: str = ""
    hook_score: float = Field(default=0.0, ge=0.0, le=1.0)
    retention_score: float = Field(default=0.0, ge=0.0, le=1.0)
    payoff_score: float = Field(default=0.0, ge=0.0, le=1.0)
    originality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    platform_fit_score: float = Field(default=0.0, ge=0.0, le=1.0)
    retention_risks: List[str] = Field(default_factory=list)
