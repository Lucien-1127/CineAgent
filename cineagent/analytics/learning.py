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
    shown_in_feed: int = 0
    average_view_duration: float = 0.0
    average_percentage_viewed: float = 0.0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    replays: int = 0
    follows: int = 0
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
    chose_to_view_rate: Optional[float] = None
    hook_retention_avg: Optional[float] = None
    share_rate: Optional[float] = None
    replay_rate: Optional[float] = None


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
            view_rates = [
                x.chose_to_view / x.shown_in_feed
                for x in items if x.shown_in_feed > 0
            ]
            hook_retention = [
                x.retention_curve[min(2, len(x.retention_curve) - 1)]
                for x in items if x.retention_curve
            ]
            total_views = sum(x.views for x in items)
            chose_rate = _average(view_rates)
            hook_rate = _average(hook_retention)
            share_rate = (
                sum(x.shares for x in items) / total_views if total_views else None
            )
            replay_rate = (
                sum(x.replays for x in items) / total_views if total_views else None
            )
            out.append(ContentInsight(
                strategy=key, samples=len(items),
                retention_avg=round(avg_ret, 3),
                note=_next_experiment(chose_rate, hook_rate, share_rate),
                chose_to_view_rate=_rounded(chose_rate),
                hook_retention_avg=_rounded(hook_rate),
                share_rate=_rounded(share_rate),
                replay_rate=_rounded(replay_rate),
            ))
        return out

    def all_metrics(self) -> List[VideoMetrics]:
        return [m for v in self._by_strategy.values() for m in v]


def _average(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _rounded(value: Optional[float]) -> Optional[float]:
    return round(value, 4) if value is not None else None


def _next_experiment(
    chose_rate: Optional[float],
    hook_retention: Optional[float],
    share_rate: Optional[float],
) -> str:
    """Choose the next experiment using transparent, configurable heuristics."""
    if chose_rate is not None and chose_rate < 0.5:
        return "test first-frame and hook variants to reduce swipe-away"
    if hook_retention is not None and hook_retention < 60.0:
        return "compress the first three seconds and deliver the promise earlier"
    if share_rate is not None and share_rate < 0.01:
        return "strengthen the useful or surprising payoff to earn shares"
    return "preserve this hook-to-payoff pattern and test one variable at a time"
