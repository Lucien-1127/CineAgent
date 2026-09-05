"""Phase 4 tests: audio-first timeline + captions + media utils."""
import asyncio

import pytest

from cineagent.domain import (
    MasterTimeline,
    ScriptPackage,
    TimelineKind,
    Word,
)
from cineagent.media.captions import build_srt, group_caption_words
from cineagent.orchestration import MissingTimestampsError, build_master_timeline, scene_timing_of
from cineagent.providers.audio import AudioProvider, TTSRequest, TTSResult
from cineagent.providers.audio.mock import MockAudioProvider


def _pkg():
    return ScriptPackage(
        hook="開場鉤子",
        narration="",
        scenes=[
            {"scene_id": "s1", "narration": "第一幕敘述文字。", "title": "開場", "goal": "吸引"},
            {"scene_id": "s2", "narration": "第二幕展開。", "title": "主體", "goal": "說明"},
        ],
        script_strategy="short_viral",
        platform="shorts",
        metadata={},
    )


def _run(coro):
    return asyncio.run(coro)


def test_master_timeline_drives_from_audio_duration():
    audio = MockAudioProvider()
    tl = _run(build_master_timeline(audio, _pkg(), voice="v1"))
    assert isinstance(tl, MasterTimeline)
    assert tl.duration > 0.0
    # +1 hook segment => 3 narration segments
    assert len(tl.segments) == 3
    # segments are sequential with no overlap
    for a, b in zip(tl.segments, tl.segments[1:]):
        assert b.start >= a.end
    # duration equals last segment end
    assert abs(tl.duration - tl.segments[-1].end) < 1e-6
    # captions derived from word timestamps (never empty)
    assert tl.captions


def test_scene_timing_maps_scene_ids():
    audio = MockAudioProvider()
    tl = _run(build_master_timeline(audio, _pkg()))
    timing = scene_timing_of(tl, _pkg().scenes)
    assert set(timing.keys()) == {"s1", "s2"}
    s1, s2 = timing["s1"], timing["s2"]
    assert s1[1] <= s2[0]  # s2 starts after s1 ends


def test_scene_timing_maps_repeated_narration_sequentially():
    pkg = ScriptPackage(
        hook="獨立鉤子",
        narration="",
        scenes=[
            {"scene_id": "s1", "narration": "重複旁白。", "title": "一", "goal": "一"},
            {"scene_id": "s2", "narration": "重複旁白。", "title": "二", "goal": "二"},
        ],
        script_strategy="short_viral",
        platform="shorts",
        metadata={},
    )
    tl = _run(build_master_timeline(MockAudioProvider(), pkg))
    timing = scene_timing_of(tl, pkg.scenes)
    assert timing["s1"] != timing["s2"]
    assert timing["s1"][1] <= timing["s2"][0]


def test_caption_grouping_and_srt():
    words = [
        Word(text="你", start=0.0, end=0.25),
        Word(text="好", start=0.25, end=0.5),
        Word(text="世", start=0.5, end=0.75),
        Word(text="界", start=0.75, end=1.0),
    ]
    cues = group_caption_words(words, max_chars=2)
    assert cues[0].text == "你好"
    srt = build_srt(cues)
    assert "你好" in srt
    assert "00:00:00,000 --> 00:00:00,500" in srt


def test_provider_without_timestamps_raises():
    class NoTS(AudioProvider):
        name = "no-ts"

        @property
        def provides_native_timestamps(self) -> bool:
            return False

        async def synthesize(self, req: TTSRequest) -> TTSResult:
            return TTSResult(audio_uri="x.wav", duration=1.0, words=[])

    with pytest.raises(MissingTimestampsError):
        _run(build_master_timeline(NoTS(), _pkg()))
