"""Analytics: collector + content learning store.

Important guardrail: an LLM must NOT mutate global rules from a single video's
result. Learning only forms after a minimum sample set (min_samples).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class VideoMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_ref: str = ""
    views: int = 0
    engaged_views: int = 0
    chose_to_view: int = 0
    average_view_duration: float = 0.0
    average_percentage_viewed: float = 0.0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    retention_curve: List[float] = Field(default_factory=list)  # % at each second
    spikes: List[float] = Field(default_factory=list)
    dips: List[float] = Field(default_factory=list)
    hook: str = ""
    script_strategy: str = ""
    duration: float = 0.0
    shot_count: int = 0
    visual_style: str = ""
    voice: str = ""
    posting_metadata: Dict[str, str] = Field(default_factory=dict)


@dataclass
class ContentInsight:
    strategy: str
    samples: int
    retention_avg: float
    note: str


class ContentLearningStore:
    """Accumulates per-strategy aggregates; exposes learning only at min_samples."""

    def __init__(self, min_samples: int = 5) -> None:
        self.min_samples = min_samples
        self._by_strategy: Dict[str, List[VideoMetrics]] = {}

    def record(self, metrics: VideoMetrics) -> None:
        self._by_strategy.setdefault(metrics.script_strategy, []).append(metrics)

    @property
    def sample_count(self) -> int:
        return sum(len(v) for v in self._by_strategy.values())

    def insights(self, strategy: str = "") -> List[ContentInsight]:
        out: List[ContentInsight] = []
        for key, items in self._by_strategy.items():
            if strategy and key != strategy:
                continue
            if len(items) < self.min_samples:
                continue  # not enough samples -> no learning
            avg_ret = sum(x.average_percentage_viewed for x in items) / len(items)
            out.append(ContentInsight(
                strategy=key, samples=len(items),
                retention_avg=round(avg_ret, 3),
                note=f"retention above threshold for '{key}'"
                     if avg_ret >= 25.0 else "retention below threshold",
            ))
        return out

    def all_metrics(self) -> List[VideoMetrics]:
        return [m for v in self._by_strategy.values() for m in v]
