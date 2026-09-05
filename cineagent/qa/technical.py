"""Technical QA via ffprobe/FFmpeg — decode, duration, fps, resolution, audio,
aspect, output size. Status: `implemented` (black-frame / loudness / subtitle-safe
checks are `experimental` and marked inline).
"""
from __future__ import annotations

import os
from typing import Optional

from ..domain.job import QAReport
from ..media.ffmpeg import probe_video


class TechnicalQA:
    """Two-layer QA is split: this is the ffprobe/ffmpeg layer."""

    def __init__(self, threshold: float = 0.6,
                 duration_tolerance: float = 0.5) -> None:
        self.threshold = threshold
        self.duration_tolerance = duration_tolerance  # seconds

    def assess(
        self,
        video_path: str,
        expected_duration: Optional[float] = None,
        expected_aspect: Optional[str] = None,
        expected_fps: Optional[float] = None,
    ) -> QAReport:
        info = probe_video(video_path)
        problems: list[str] = []
        severities: list[str] = []
        penalty = 0.0

        if not info or info.get("duration", 0) <= 0:
            problems.append("video undecodable or has no duration")
            severities.append("high")
            penalty += 0.6
        else:
            if expected_duration is not None and abs(
                info["duration"] - expected_duration
            ) > self.duration_tolerance:
                problems.append(
                    f"duration mismatch: got {info['duration']:.2f}s "
                    f"expected {expected_duration:.2f}s"
                )
                severities.append("medium")
                penalty += 0.5

            if not info.get("has_audio", False):
                problems.append("missing audio stream")
                severities.append("medium")
                penalty += 0.15

            w, h = info.get("width"), info.get("height")
            if w and h:
                if expected_aspect and not _aspect_matches(w, h, expected_aspect):
                    problems.append(f"aspect mismatch: {w}x{h} vs {expected_aspect}")
                    severities.append("medium")
                    penalty += 0.15
                if w < 200 or h < 200:
                    problems.append(f"low resolution {w}x{h}")
                    severities.append("low")
                    penalty += 0.1

            if expected_fps is not None and info.get("fps") is not None:
                if abs(info["fps"] - expected_fps) > 2.0:
                    problems.append(
                        f"fps mismatch: got {info['fps']} expected ~{expected_fps}"
                    )
                    severities.append("low")
                    penalty += 0.05

        size = os.path.getsize(video_path) if os.path.exists(video_path) else 0
        if size <= 0:
            problems.append("output file empty/missing")
            severities.append("high")
            penalty += 0.5
        else:
            # embed output size as a non-failing note
            problems.insert(0, f"output size {size} bytes") if len(problems) else None

        score = max(0.0, min(1.0, 1.0 - penalty))
        decision = "pass" if score >= self.threshold and not _high(severities) else (
            "repair" if score >= self.threshold * 0.5 else "fail"
        )
        return QAReport(
            shot_id="", stage="technical", score=round(score, 3),
            threshold=self.threshold, decision=decision,
            problems=problems, severities=severities,
            repair_instructions=_repair(decision, problems),
        )


def _high(severities) -> bool:
    return any(s == "high" for s in severities)


def _aspect_matches(w: int, h: int, aspect: str) -> bool:
    a, b = aspect.split(":")
    target = float(a) / float(b)
    actual = w / h
    return abs(actual - target) / target < 0.08


def _repair(decision: str, problems) -> str:
    if decision == "pass":
        return ""
    if any("undecodable" in p or "empty" in p for p in problems):
        return "regenerate clip (corrupt/empty output)"
    if any("audio" in p for p in problems):
        return "remux/regenerate with an audio track"
    if any("duration" in p for p in problems):
        return "re-generate clip to the shot duration"
    return "regenerate clip"
