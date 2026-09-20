"""Stitching: frame extraction, linking, overlap trimming, degradation."""
import asyncio
import os
import shutil

import pytest

from cineagent.media.ffmpeg import probe_video
from cineagent.orchestration import link_segments, stitch_segments
from conftest import make_video

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)


def test_link_segments_extracts_last_frames(tmp_path):
    v0 = make_video(str(tmp_path / "s0.mp4"), duration=2, color="red")
    v1 = make_video(str(tmp_path / "s1.mp4"), duration=2, color="blue")
    report = link_segments([v0, v1], str(tmp_path / "link"))
    assert report.segment_count == 2
    assert "0" in report.last_frame_paths
    assert os.path.exists(report.last_frame_paths["0"])
    assert report.frame_sources["1"] == report.last_frame_paths["0"]
    assert report.degraded_to_prompt_continuity == []


def test_link_segments_degrades_on_missing_file(tmp_path):
    missing = str(tmp_path / "nope.mp4")
    v1 = make_video(str(tmp_path / "s1.mp4"), duration=1)
    report = link_segments([missing, v1], str(tmp_path / "link"))
    assert 1 in report.degraded_to_prompt_continuity
    assert len(report.failures) == 1


def test_stitch_segments_produces_playable_output(tmp_path):
    v0 = make_video(str(tmp_path / "a.mp4"), duration=2, color="red")
    v1 = make_video(str(tmp_path / "b.mp4"), duration=2, color="blue")
    out = str(tmp_path / "final.mp4")
    asyncio.run(stitch_segments(
        [v0, v1], [2.0, 2.0], overlap_seconds=0.0, output_path=out,
        aspect="9:16", fps=30, workdir=str(tmp_path / "w"),
    ))
    assert os.path.exists(out)
    info = probe_video(out)
    assert info["width"] > 0
    assert info["duration"] > 0


def test_stitch_trims_overlap(tmp_path):
    v0 = make_video(str(tmp_path / "a.mp4"), duration=2, color="red")
    v1 = make_video(str(tmp_path / "b.mp4"), duration=2, color="blue")
    v2 = make_video(str(tmp_path / "c.mp4"), duration=2, color="green")
    out = str(tmp_path / "final.mp4")
    asyncio.run(stitch_segments(
        [v0, v1, v2], [2.0, 2.0, 2.0], overlap_seconds=0.5, output_path=out,
        aspect="9:16", fps=30, workdir=str(tmp_path / "w"),
    ))
    info = probe_video(out)
    # 2 + (2-0.5) + (2-0.5) = 5.0 (vs 6.0 without trimming)
    assert abs(info["duration"] - 5.0) < 0.6
