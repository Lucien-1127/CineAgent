"""Canonical timing data — the single source of truth for all temporal layout.

Captions, shots, transitions, and the renderer all read from this structure;
nobody re-guesses timing from a per-scene default.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TimelineKind(str, Enum):
    NARRATION = "narration"
    DIALOGUE = "dialogue"
    AMBIENCE = "ambience"
    SFX = "sfx"
    MUSIC = "music"


class Word(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    start: float
    end: float


class CaptionCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    start: float
    end: float


class TimelineSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TimelineKind = TimelineKind.NARRATION
    text: str = ""
    start: float = 0.0
    end: float = 0.0
    audio_uri: str = ""  # synthesized audio for this segment (if any)
    words: List[Word] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class MasterTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: List[TimelineSegment] = Field(default_factory=list)
    source_script_id: str = ""
    duration: float = 0.0

    @property
    def captions(self) -> List[CaptionCue]:
        cues: List[CaptionCue] = []
        for seg in self.segments:
            if seg.kind in (TimelineKind.NARRATION, TimelineKind.DIALOGUE):
                if seg.words:
                    # word-level cues, merging into short sub-caption groups later
                    for w in seg.words:
                        if cues and abs(cues[-1].end - w.start) < 0.05:
                            cues[-1] = CaptionCue(
                                text=cues[-1].text + w.text, start=cues[-1].start, end=w.end
                            )
                        else:
                            cues.append(CaptionCue(text=w.text, start=w.start, end=w.end))
                else:
                    cues.append(CaptionCue(text=seg.text, start=seg.start, end=seg.end))
        return cues
