"""Unified, provider-neutral video generation request/status models.

These are the canonical structures exchanged between the pipeline/planner and
any video provider (Seedance / Kling / mock). Vendor payloads are assembled
inside each adapter from these neutral fields; the pipeline never builds a
vendor request body directly.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class VideoTaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class VideoGenerationRequest(BaseModel):
    """Neutral request: *what* to generate, not how any vendor serializes it.

    A single type covers text-to-video, image-to-video, and first/last-frame
    requests. The adapter is responsible for validating a requested feature
    against the target model's capability matrix and for dropping UNVERIFIED or
    unsupported fields rather than forwarding them.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    prompt: str
    negative_prompt: str = ""
    image_url: Optional[str] = None          # first frame (image-to-video)
    start_frame_url: Optional[str] = None    # explicit alias of image_url
    end_frame_url: Optional[str] = None      # last frame (first+last-frame mode)
    reference_images: List[str] = Field(default_factory=list)
    reference_videos: List[str] = Field(default_factory=list)
    audio_url: Optional[str] = None          # reference audio (native-audio models)
    duration_seconds: int = Field(default=5, ge=1)
    aspect_ratio: str = "9:16"
    resolution: str = "720p"
    native_audio: bool = False
    multi_shot: bool = False
    seed: Optional[int] = None
    idempotency_key: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def first_frame(self) -> Optional[str]:
        return self.start_frame_url or self.image_url

    def features(self) -> List[str]:
        """The capability flags a capability router would test against."""
        feats: List[str] = []
        if self.prompt and not self.first_frame:
            feats.append("text_to_video")
        if self.first_frame:
            feats.append("image_to_video")
        if self.first_frame and self.end_frame_url:
            feats.append("first_frame")
            feats.append("last_frame")
        if self.reference_images:
            feats.append("reference_image")
        if self.reference_videos:
            feats.append("reference_video")
        if self.audio_url:
            feats.append("reference_audio")
        if self.native_audio:
            feats.append("audio_generation")
        return feats


class VideoTask(BaseModel):
    """Handle to a submitted remote generation task."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    remote_job_id: str
    status: VideoTaskState = VideoTaskState.QUEUED


class VideoTaskStatus(BaseModel):
    """Resolved task status returned by a provider query."""

    model_config = ConfigDict(extra="forbid")

    remote_job_id: str
    state: VideoTaskState
    video_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.state in (
            VideoTaskState.SUCCEEDED,
            VideoTaskState.FAILED,
            VideoTaskState.EXPIRED,
        )


__all__ = [
    "VideoGenerationRequest",
    "VideoTask",
    "VideoTaskState",
    "VideoTaskStatus",
]
