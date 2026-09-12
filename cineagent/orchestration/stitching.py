"""Segment stitching and seam handling.

Chain segments: extract each segment's last frame and feed it as the next
segment's first frame (when the provider supports first/last frames), record
frame sources, deduplicate the overlap, and concatenate into a final video.

Degradation: when last-frame extraction fails, the next segment falls back to
prompt continuity (the failure is recorded, the pipeline is NOT falsely marked
complete).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..media.ffmpeg import MediaCommandError, MediaToolMissing, extract_last_frame
from ..renderer.ffmpeg import FFmpegRenderer
from ..renderer.base import RenderComposition, RenderSegment


class SeamReport(BaseModel):
    """What the stitching step did, and what it could not do."""

    model_config = ConfigDict(extra="forbid")

    segment_count: int = 0
    last_frame_paths: Dict[str, str] = Field(default_factory=dict)  # seg_id -> path
    frame_sources: Dict[str, str] = Field(default_factory=dict)     # seg_id -> description
    degraded_to_prompt_continuity: List[int] = Field(default_factory=list)
    failures: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


def extract_last_frame_safe(video_path: str, out_path: str, pad: float = 0.0) -> Optional[str]:
    """Extract a segment's final frame, returning None (never raising) on failure."""
    try:
        return extract_last_frame(video_path, out_path, pad=pad)
    except (MediaCommandError, MediaToolMissing) as exc:
        # Caller records the failure; the pipeline is not marked complete.
        return None


def link_segments(
    segment_videos: List[str],
    workdir: str,
    pad: float = 0.0,
) -> SeamReport:
    """Extract each segment's last frame and link it to the next segment.

    ``segment_videos`` is ordered. For i in [0, n-2], extract the last frame of
    segment i into ``workdir/last_frame_<i>.png`` and record it as segment
    i+1's start-frame source. A failure only degrades that link; it does not
    abort the chain.
    """
    report = SeamReport(segment_count=len(segment_videos))
    d = Path(workdir)
    d.mkdir(parents=True, exist_ok=True)
    for i in range(len(segment_videos) - 1):
        out = str(d / f"last_frame_{i}.png")
        path = extract_last_frame_safe(segment_videos[i], out, pad=pad)
        if path is None:
            report.failures.append(
                f"segment {i}: last-frame extraction failed; "
                f"segment {i + 1} degrades to prompt continuity"
            )
            report.degraded_to_prompt_continuity.append(i + 1)
            report.frame_sources[str(i + 1)] = "prompt_continuity (extraction failed)"
        else:
            report.last_frame_paths[str(i)] = path
            report.frame_sources[str(i + 1)] = path
    return report


async def stitch_segments(
    segment_videos: List[str],
    segment_durations: List[float],
    overlap_seconds: float,
    output_path: str,
    aspect: str = "9:16",
    fps: int = 30,
    workdir: str = "/tmp/cineagent-stitch",
) -> str:
    """Trim each segment's overlap head and concat into one video.

    Segment i>0 has its first ``overlap_seconds`` trimmed (the duplicate region
    shared with segment i-1). Re-encodes via FFmpegRenderer so the concat is
    codec-consistent, then verifies the output is playable.
    """
    if not segment_videos:
        raise ValueError("no segments to stitch")
    segments: List[RenderSegment] = []
    for i, video in enumerate(segment_videos):
        trim = overlap_seconds if i > 0 else 0.0
        duration = max(0.2, segment_durations[i] - trim)
        segments.append(RenderSegment(path=video, start=trim,
                                      duration=duration, kind="video"))
    comp = RenderComposition(
        output_path=output_path, aspect=aspect, fps=fps, segments=segments,
    )
    await FFmpegRenderer(workdir=workdir).render(comp)
    return output_path


__all__ = ["SeamReport", "extract_last_frame_safe", "link_segments", "stitch_segments"]
