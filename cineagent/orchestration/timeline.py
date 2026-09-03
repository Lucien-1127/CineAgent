"""Audio-first timeline builder.

Order: Final Script -> TTS -> Timing Alignment -> Master Timeline.
Shots/captions/transitions all read from the returned MasterTimeline; nobody
re-guesses duration from a per-scene default.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from ..domain.script import ScriptPackage
from ..domain.timeline import MasterTimeline, TimelineKind, TimelineSegment, Word
from ..providers.audio.base import AudioProvider

SEGMENT_GAP = 0.25  # small breathing room between narration segments


class MissingTimestampsError(RuntimeError):
    """Provider returned no word timestamps and no aligner is configured."""


async def build_master_timeline(
    audio: AudioProvider,
    pkg: ScriptPackage,
    voice: str = "default",
) -> MasterTimeline:
    """Synthesize narration per scene, align, and lay segments on one timeline.

    When the provider has native timestamps they are used directly. Otherwise a
    forced-alignment / STT aligner is required (marked `planned`); we raise
    rather than guess.
    """
    segments: List[TimelineSegment] = []
    cursor = 0.0

    async def place(text: str, kind: TimelineKind) -> TimelineSegment:
        nonlocal cursor
        res = await audio.synthesize(TTSRequest_from(text, voice))
        seg = TimelineSegment(
            kind=kind,
            text=text,
            start=round(cursor, 3),
            end=round(cursor + res.duration, 3),
            audio_uri=res.audio_uri,
        )
        if res.words:
            shift = cursor - res.words[0].start if res.words else 0.0
            seg.words = [Word(text=w.text, start=round(w.start + shift, 3),
                              end=round(w.end + shift, 3)) for w in res.words]
        elif text.strip():
            # provider native=false and no aligner configured => fail loudly
            raise MissingTimestampsError(
                "AudioProvider gave no word timestamps and no forced-alignment "
                "aligner is configured. Refusing to guess caption timing."
            )
        segments.append(seg)
        cursor = seg.end + SEGMENT_GAP
        return seg

    if pkg.hook and (not pkg.scenes or pkg.scenes[0].narration != pkg.hook):
        await place(pkg.hook, TimelineKind.NARRATION)

    for scene in pkg.scenes:
        if scene.narration:
            await place(scene.narration, TimelineKind.NARRATION)

    dur = segments[-1].end if segments else 0.0
    return MasterTimeline(segments=segments, duration=round(dur, 3),
                          source_script_id=pkg.metadata.get("script_id", ""))


def scene_timing_of(timeline: MasterTimeline, scenes) -> Dict[str, Tuple[float, float]]:
    """Map scene_id -> (start, end) from narration segments.

    Segments are matched to scenes by narration text, which robustly skips a
    leading hook segment (hook text != any scene's narration).
    """
    by_text: Dict[str, Tuple[float, float]] = {}
    for seg in timeline.segments:
        if seg.kind == TimelineKind.NARRATION and seg.text:
            by_text.setdefault(seg.text, (seg.start, seg.end))
    mapping: Dict[str, Tuple[float, float]] = {}
    for scene in scenes:
        if scene.narration and scene.narration in by_text:
            mapping[scene.scene_id] = by_text[scene.narration]
    return mapping


def TTSRequest_from(text: str, voice: str):
    from ..providers.audio.base import TTSRequest
    return TTSRequest(text=text, voice=voice, language="zh-TW")
