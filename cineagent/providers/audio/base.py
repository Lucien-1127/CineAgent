"""AudioProvider contract — TTS / dialogue with optional native timestamps."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from ...domain.timeline import Word


@dataclass
class TTSRequest:
    text: str
    voice: str = "default"
    language: str = "zh-TW"
    speed: float = 1.0
    settings: Optional[dict] = None


@dataclass
class TTSResult:
    audio_uri: str
    duration: float
    words: List[Word] = field(default_factory=list)  # empty => alignment required
    native: bool = False  # true if timestamps came from the provider


class AudioProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def synthesize(self, req: TTSRequest) -> TTSResult:
        raise NotImplementedError

    @property
    def provides_native_timestamps(self) -> bool:
        return False
