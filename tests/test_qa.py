"""Phase 9 tests: Technical QA (ffprobe) + Mock Visual QA."""
import asyncio

import pytest

from cineagent.domain import QAReport, ShotSpec
from cineagent.media.ffmpeg import MediaToolMissing
from cineagent.qa import MockVisualQA, TechnicalQA
from cineagent.renderer import (
    FFmpegRenderer,
    RenderComposition,
    RenderSegment,
    make_test_media,
)


def _run(coro):
    return asyncio.run(coro)


def _render(out_path: str, with_audio: bool = True) -> str:
    try:
        img, wav = make_test_media("/tmp/cineagent-qa-smoke-assets")
    except MediaToolMissing:
        pytest.skip("ffmpeg not installed")
    segments = [
        RenderSegment(path=img, start=0.0, duration=1.0, kind="image"),
        RenderSegment(path=img, start=1.0, duration=1.0, kind="image"),
    ]
    comp = RenderComposition(
        output_path=out_path,
        aspect="9:16", fps=24,
        segments=segments,
        audio=(wav if with_audio else None),
    )
    return _run(FFmpegRenderer().render(comp))


def test_technical_qa_passes_good_video():
    path = _render("/tmp/cineagent-qa-smoke/qa_good.mp4")
    rep = TechnicalQA().assess(path, expected_duration=2.0, expected_aspect="9:16", expected_fps=24.0)
    assert rep.stage == "technical"
    assert rep.passed is True
    assert rep.score >= rep.threshold


def test_technical_qa_flags_duration_mismatch():
    path = _render("/tmp/cineagent-qa-smoke/qa_mismatch.mp4")
    rep = TechnicalQA(duration_tolerance=0.05).assess(path, expected_duration=99.0)
    assert rep.passed is False
    assert any("duration" in p for p in rep.problems)


def test_technical_qa_output_file_exists():
    path = _render("/tmp/cineagent-qa-smoke/qa_exists.mp4", with_audio=False)
    # renderer muxes a silent audio track, so the file should still decode/avaudio
    rep = TechnicalQA().assess(path)
    assert rep.passed is True


def test_visual_qa_mock_passes():
    rep = _run(MockVisualQA().assess(
        "/tmp/x.mp4", ShotSpec(shot_id="s1", scene_id="sc1"),)
    )
    assert rep.decision == "pass"
    assert rep.score == 1.0


def test_visual_qa_mock_flags_problems():
    rep = _run(MockVisualQA(problems=["character drift"]).assess(
        "/tmp/x.mp4", ShotSpec(shot_id="s1", scene_id="sc1"),)
    )
    assert rep.decision == "repair"
    assert "character drift" in rep.problems