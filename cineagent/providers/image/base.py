"""Image provider contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ImageRequest:
    prompt: str
    negative: List[str] = field(default_factory=list)
    aspect: str = "9:16"
    reference_images: List[str] = field(default_factory=list)
    quality_tier: str = "balanced"
    settings: Optional[dict] = None


@dataclass
class ImageResult:
    uri: str
    provider: str = ""
    model: str = ""
    estimated_cost_usd: float = 0.0


class ImageProvider(ABC):
    name = "base-image"
    model = ""

    @abstractmethod
    async def generate(self, req: ImageRequest) -> ImageResult:
        raise NotImplementedError
