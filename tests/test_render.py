"""Phase 8 tests: FFmpeg renderer smoke (real MP4) + Remotion gate."""
import asyncio

import pytest

from cineagent.media.ffmpeg import (
    MediaCommandError,
    MediaToolMissing,
    probe_video,
)
from cineagent.renderer import (
    FFmpegRenderer,
    RemotionRenderer,
    RenderComposition,
    RenderSegment,
    make_test_media,
)


def _run(coro):
    return asyncio.run(coro)


def test_ffmpeg_render_produces_playable_mp4():
    try:
        img, wav = make_test_media("/tmp/cineagent-render-smoke")
    except MediaToolMissing:
        pytest.skip("ffmpeg not installed")
    srt = "/tmp/cineagent-render-smoke/captions.srt"
    with open(srt, "w") as f:
        f.write("1\n00:00:00,000 --> 00:00:01,000\n你好世界\n\n")
    comp = RenderComposition(
        output_path="/tmp/cineagent-render-smoke/out.mp4",
        aspect="9:16", fps=24,
        segments=[
            RenderSegment(path=img, start=0.0, duration=1.0, kind="image"),
            RenderSegment(path=img, start=1.0, duration=1.0, kind="image"),
        ],
        audio=wav,
        captions_srt=srt,
    )
    out = _run(FFmpegRenderer().render(comp))
    assert out == comp.output_path
    info = probe_video(out)
    assert info["duration"] == pytest.approx(2.0, abs=0.3)
    assert info["has_audio"] is True
    assert info["width"] > 0 and info["height"] > 0


def test_ffmpeg_normalizes_mixed_segment_geometry():
    try:
        portrait, wav = make_test_media(
            "/tmp/cineagent-render-mixed", image="portrait.png", size="540x960",
        )
        landscape, _ = make_test_media(
            "/tmp/cineagent-render-mixed", image="landscape.png",
            wav="unused.wav", size="640x360",
        )
    except MediaToolMissing:
        pytest.skip("ffmpeg not installed")
    comp = RenderComposition(
        output_path="/tmp/cineagent-render-mixed/out.mp4",
        aspect="9:16",
        fps=24,
        segments=[
            RenderSegment(path=portrait, duration=0.5, kind="image"),
            RenderSegment(path=landscape, duration=0.5, kind="image"),
        ],
        audio=wav,
    )
    out = _run(FFmpegRenderer().render(comp))
    info = probe_video(out)
    assert (info["width"], info["height"]) == (540, 960)


def test_remotion_renderer_is_planned_gate():
    with pytest.raises(NotImplementedError):
        _run(RemotionRenderer().render(RenderComposition(output_path="/tmp/x.mp4")))
