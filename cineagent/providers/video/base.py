"""Video provider contract — durable, async generation.

The pipeline never guesses remote state. It persists the returned
`remote_job_id`; webhook (preferred) or polling resolves completion. A crash
must not turn an unfinished job into COMPLETE.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class VideoRequest:
    prompt: str
    duration: float
    aspect: str = "9:16"
    first_frame: Optional[str] = None
    last_frame: Optional[str] = None
    reference_images: List[str] = field(default_factory=list)
    reference_video: Optional[str] = None
    quality_tier: str = "balanced"
    candidate_index: int = 0
    idempotency_key: str = ""  # let provider skip duplicate remote submission


@dataclass
class VideoJobRef:
    provider: str
    model: str
    remote_job_id: str


@dataclass
class VideoResult:
    uri: str = ""
    state: str = "submitted"  # submitted | generating | succeeded | failed
    error: str = ""
    estimated_cost_usd: float = 0.0
    remote_job_id: str = ""


class VideoProvider(ABC):
    name = "base-video"
    model = ""
    poll_interval_s: float = 5.0
    supports_webhook: bool = False

    @abstractmethod
    async def submit(self, req: VideoRequest) -> VideoJobRef:
        """Create a remote job; MUST be idempotent on idempotency_key."""

    @abstractmethod
    async def poll(self, remote_job_id: str) -> VideoResult:
        raise NotImplementedError
