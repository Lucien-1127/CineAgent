"""Phase 5 tests: VisualBible + Storyboard sourced from the Audio Master Timeline."""
import asyncio

import pytest

from cineagent.creative import StoryboardDirector
from cineagent.domain import ScriptPackage, VisualBible, VisualCharacter
from cineagent.orchestration import build_master_timeline, scene_timing_of
from cineagent.providers.audio.mock import MockAudioProvider


def _pkg():
    return ScriptPackage(
        hook="鉤子開場",
        narration="",
        scenes=[
            {"scene_id": "s1", "narration": "第一幕敘述文字內容。", "title": "城市夜空", "goal": "建立氛圍"},
            {"scene_id": "s2", "narration": "第二幕展開情節。", "title": "主角登場", "goal": "引入主角"},
        ],
        script_strategy="storytelling",
        platform="shorts",
        metadata={},
    )


def _bible():
    return VisualBible(
        project_id="p1",
        characters={"hero": VisualCharacter(
            char_id="hero", name="小明", appearance="年輕男性，黑短髮",
            wardrobe="藍色夾克", reference_assets=["ref/hero.png"],
        )},
        wardrobe=["藍色夾克"],
        locations=["霓虹城市夜晚"],
        palette=["藍", "紫", "洋紅"],
        lighting="霓虹側光",
        art_style="寫實科幻",
        negative_constraints=["多餘手指", "文字浮水印", "卡通風"],
        continuity_rules=["主角服裝跨鏡頭一致"],
        reference_assets=["ref/style.png"],
    )


def _run(coro):
    return asyncio.run(coro)


def test_storyboard_uses_audio_timeline_for_shot_timing():
    pkg = _pkg()
    bible = _bible()
    tl = _run(build_master_timeline(MockAudioProvider(), pkg))
    timing = scene_timing_of(tl, pkg.scenes)
    director = StoryboardDirector()
    shots = director.direct(pkg, bible, timing)

    # every scene produces >=1 shot
    scene_ids = {s.scene_id for s in pkg.scenes}
    assert {sh.scene_id for sh in shots} == scene_ids
    assert len(shots) >= len(pkg.scenes)

    # shot timing is audio-driven, not guessed to a fixed default
    for sh in shots:
        assert sh.duration > 0.0, "shot duration must derive from audio timeline"
        assert sh.end_time == pytest.approx(sh.start_time + sh.duration)
        assert sh.reference_images, "reference-first: bible reference assets propagate"
        assert sh.provider_constraints, "negative constraints propagate from bible"


def test_shots_are_sequential_inside_timeline():
    pkg = _pkg()
    tl = _run(build_master_timeline(MockAudioProvider(), pkg))
    timing = scene_timing_of(tl, pkg.scenes)
    shots = StoryboardDirector().direct(pkg, _bible(), timing)
    for a, b in zip(shots, shots[1:]):
        assert b.start_time >= a.end_time - 1e-6


def test_director_matches_scene_span_to_narration():
    pkg = _pkg()
    tl = _run(build_master_timeline(MockAudioProvider(), pkg))
    timing = scene_timing_of(tl, pkg.scenes)
    shots = StoryboardDirector().direct(pkg, _bible(), timing)
    # total scene-shot duration equals the sum of scene narration spans on the
    # audio timeline (the leading hook segment is excluded from scene shots)
    expected = sum(end - start for (start, end) in timing.values())
    total = sum(sh.duration for sh in shots)
    assert total == pytest.approx(expected, abs=0.05)
