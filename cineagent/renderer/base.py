"""Renderer contract. AI generation produces clips; the renderer composes them."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RenderSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str            # video file or still image
    start: float = 0.0   # start in the output timeline (seconds)
    duration: float = 0.0
    kind: str = "video"  # video | image


class RenderComposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_path: str
    aspect: str = "9:16"
    fps: int = 30
    segments: List[RenderSegment] = Field(default_factory=list)
    audio: Optional[str] = None          # narration/music mix path
    captions_srt: Optional[str] = None   # burn-in captions
    title: Optional[str] = None          # hook overlay text (planned with Remotion)

    @property
    def duration(self) -> float:
        return max((s.start + s.duration for s in self.segments), default=0.0)


class RendererProvider(ABC):
    """Turns a RenderComposition into a final playable file (e.g. MP4).

    Responsible for: timeline, clips, image animation, transitions, subtitles,
    captions, title/hook overlay, watermark/logo, end card, BGM, audio ducking,
    SFX, platform aspect. Generation models never own final typography.
    """

    name = "base-renderer"
    status = "planned"  # implemented | experimental | planned

    @abstractmethod
    async def render(self, comp: RenderComposition) -> str:
        """Render and return the output file path."""
        raise NotImplementedError
