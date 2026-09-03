"""E2E smoke: Topic -> Script -> Voice -> Timeline -> Shots -> Assets -> Render -> MP4.

Runs entirely offline with Mock providers. Exercises the canonical pipeline.
"""
import asyncio
import os

import pytest

from cineagent.assets import AssetLibrary, AssetRouter, TokenHashEmbedder
from cineagent.creative import PromptCompiler, ScriptEngine, StoryboardDirector
from cineagent.domain import Asset, AssetSource, AssetType
from cineagent.domain.enums import ScriptStrategy
from cineagent.orchestration import build_master_timeline, scene_timing_of
from cineagent.providers.audio.mock import MockAudioProvider
from cineagent.providers.text.mock import MockTextProvider
from cineagent.qa import TechnicalQA
from cineagent.renderer import (
    FFmpegRenderer,
    RenderComposition,
    RenderSegment,
    make_test_media,
)
from cineagent.storage.database import Database
from cineagent.storage.repositories import AssetRepo, ensure_schema


def _run(coro):
    return asyncio.run(coro)


def _text_provider():
    p = MockTextProvider()

    def handler(schema):
        from cineagent.domain import CreativeBrief, HookSet
        from cineagent.domain.script import HookCandidate, CritiqueResult
        if schema is CreativeBrief:
            return {"audience": "大眾", "core_message": "AI 讓創作更快",
                    "emotional_goal": "啟發", "content_type": "短影音",
                    "references": [], "prohibited_elements": [],
                    "cta_strategy": "追蹤"}
        if schema is HookSet:
            return HookSet(candidates=[
                HookCandidate(text="AI 三秒創作", score=0.9),
                HookCandidate(text="為何要學 AI", score=0.6),
                HookCandidate(text="創作被取代?", score=0.4),
            ])
        if schema is CritiqueResult:
            return {"passed": True, "notes": [], "revision_guidance": ""}
        if schema.__name__ == "ScriptPackage":
            return {"hook": "AI 三秒創作",
                    "narration": "AI 改變創作。你也能用。",
                    "scenes": [
                        {"scene_id": "s1", "narration": "AI 改變創作。",
                         "title": "開場", "goal": "吸引"},
                        {"scene_id": "s2", "narration": "你也能用。",
                         "title": "主體", "goal": "說明"},
                    ],
                    "facts": [], "cta": "追蹤我", "metadata": {},
                    "script_strategy": "short_viral",
                    "expected_duration": 8.0, "platform": "shorts"}
        raise AssertionError(f"unexpected schema {schema}")

    p.handler = handler
    return p


def test_e2e_full_mainline_produces_mp4():
    # 1) Script
    pkg = _run(ScriptEngine().run(_text_provider(), "AI 創作", ScriptStrategy.SHORT_VIRAL))
    assert pkg.hook and pkg.scenes

    # 2) Voice -> Master Timeline (audio-first)
    tl = _run(build_master_timeline(MockAudioProvider(), pkg))
    assert tl.duration > 0 and tl.captions

    # 3) Storyboard -> ShotSpecs with audio-driven timing
    timing = scene_timing_of(tl, pkg.scenes)
    shots = StoryboardDirector().direct(pkg, None, timing)
    assert shots and all(s.duration > 0 for s in shots)

    # 4) Assets: prompt compile -> mock image -> library route
    db = Database(":memory:")
    ensure_schema(db)
    lib = AssetLibrary(AssetRepo(db), TokenHashEmbedder())
    router = AssetRouter(lib, threshold=0.95)
    pc = PromptCompiler()
    workdir = "/tmp/cineagent-e2e"
    segments = []
    cursor = 0.0
    for i, shot in enumerate(shots):
        payload = pc.compile(shot, "agnostic")
        # use a real still from make_test_media as a stand-in generated image
        img, _ = make_test_media(workdir)
        lib.add(Asset(asset_id=f"a-{i}", project_id="p-e2e",
                      source=AssetSource.GENERATED, type=AssetType.IMAGE,
                      uri=img, tags=["city"], hash=f"h{i}"))
        decision = router.route(shot, project_id="p-e2e",
                                query="城市 夜景 霓虹")
        assert decision.action in ("reuse_library", "generate")
        segments.append(RenderSegment(path=img, start=cursor,
                                      duration=shot.duration, kind="image"))
        cursor += shot.duration

    # 5) Render -> final MP4
    srt = f"{workdir}/cap.srt"
    with open(srt, "w") as f:
        f.write("1\n00:00:00,000 --> 00:00:01,000\nAI 創作\n\n")
    out = f"{workdir}/final.mp4"
    comp = RenderComposition(output_path=out, aspect="9:16", fps=24,
                             segments=segments, captions_srt=srt)
    _run(FFmpegRenderer().render(comp))
    assert os.path.exists(out)

    # 6) Technical QA on the final file
    rep = TechnicalQA().assess(out, expected_duration=cursor)
    assert rep.stage == "technical"
    assert rep.passed is True
