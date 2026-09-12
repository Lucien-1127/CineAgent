"""Video providers package."""
from .base import VideoJobRef, VideoProvider, VideoRequest, VideoResult
from .generation import GenerationProvider, download_video
from .schemas import (
    VideoGenerationRequest,
    VideoTask,
    VideoTaskState,
    VideoTaskStatus,
)

__all__ = [
    "GenerationProvider",
    "VideoGenerationRequest",
    "VideoJobRef",
    "VideoProvider",
    "VideoRequest",
    "VideoResult",
    "VideoTask",
    "VideoTaskState",
    "VideoTaskStatus",
    "download_video",
]
