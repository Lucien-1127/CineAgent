"""AnalyticsCollector — records per-video performance into the learning store."""
from __future__ import annotations

from .learning import ContentLearningStore, VideoMetrics


class AnalyticsCollector:
    def __init__(self, store: ContentLearningStore) -> None:
        self.store = store

    def record(self, metrics: VideoMetrics) -> None:
        self.store.record(metrics)
