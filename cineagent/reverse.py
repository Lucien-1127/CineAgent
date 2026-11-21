"""Layer A — video reverse engineering (拆解參考影片 → beat sheet).

Pipeline: ffmpeg scene detection → per-segment frame sampling (start / middle /
end) → VLM describes each segment on a fixed rubric → :class:`BeatSheet` with a
measured :class:`Rhythm`.

Why this exists: the old pipeline planned shots from prose, which is why every
30s cut looked the same (one camera move, uniform shot length, flat energy).
Reversing a reference clip gives the planner a *measured* skeleton: real shot
lengths, real cut count, real acceleration, real move mix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import media
from .beatsheet import BeatSheet, Shot, compute_rhythm, CAMERA_MOVES, FRAMINGS
from .gate import _coerce_number
from .providers import Chat

SEGMENT_RUBRIC = """You are a shot analyst. You get three frames from ONE shot
(start, middle, end) of a reference film, in order.

Describe the shot in JSON only:
{"framing":"ECU|CU|MCU|MS|MWS|WS|EWS|OTS|POV|TWO-SHOT",
 "camera_move":"static|pan-left|pan-right|tilt-up|tilt-down|dolly-in|dolly-out|truck-left|truck-right|crane-up|crane-down|handheld|orbit|zoom-in|zoom-out|rack-focus|whip-pan",
 "camera_speed":"slow|medium|fast",
 "lens_mm":18-135,
 "lighting":"<=8 words",
 "palette":["hue1","hue2","hue3"],
 "setting":"<=12 words",
 "subject":"<=12 words",
 "action":"what physically happens during this shot, <=14 words",
 "energy":1-5,
 "cut_out":"hard|match|fade|dissolve|whip|jump|none",
 "notes":"<=15 words"}
No prose outside the JSON."""


@dataclass
class SegmentAnalysis:
    start: float
    end: float
    frames: list[str]
    data: dict

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 2)


def _safe_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON in segment analysis")
    blob = text[start:end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        import re
        return json.loads(re.sub(r",\s*}", "}", blob))


def analyse_segment(chat: Chat, frames: list[str], start: float, end: float) -> dict:
    from .providers import image_content

    parts: list[dict] = [{"type": "text",
                          "text": f"Shot spans {start:.2f}s–{end:.2f}s "
                                  f"({end - start:.2f}s). Frames follow in order."}]
    for frame in frames:
        parts.append(image_content(frame))
    parts.append({"type": "text", "text": SEGMENT_RUBRIC})
    text = chat.complete([{"role": "user", "content": parts}],
                         temperature=0.2, max_tokens=700, json_mode=True)
    return _safe_json(text)


def fallback_shot(index: int, start: float, end: float) -> Shot:
    duration = max(1.0, round(end - start, 2))
    return Shot(index=index, duration=duration, framing="MS", camera_move="static",
                camera_speed="medium", lens_mm=35,
                setting="unknown", subject="unknown", action="unknown",
                energy=3, cut_type="hard", notes="heuristic (VLM unavailable)")


class ReverseEngine:
    """Turn a reference video into a beat sheet."""

    def __init__(self, chat: Chat, threshold: float = 0.30, max_shots: int = 12,
                 workdir: str | Path | None = None):
        self.chat = chat
        self.threshold = threshold
        self.max_shots = max_shots
        self.workdir = Path(workdir or ".cineagent_frames")

    def analyse(self, video: str | Path, title: str = "") -> BeatSheet:
        info = media.probe(video)
        spans = media.segments(video, self.threshold, self.max_shots)
        if not spans:
            raise media.MediaError("no shots detected — try a lower --threshold")

        analyses: list[SegmentAnalysis] = []
        for i, (start, end) in enumerate(spans):
            times = [start + (end - start) * f for f in (0.1, 0.5, 0.9)]
            frames = [str(p) for p in media.sample_frames(
                video, times, self.workdir / "segments", prefix=f"seg{i:02d}")]
            try:
                data = analyse_segment(self.chat, frames, start, end)
            except Exception as exc:  # VLM down → keep the rhythm, lose the detail
                data = {"_error": str(exc)[:200]}
            analyses.append(SegmentAnalysis(start, end, frames, data))

        shots: list[Shot] = []
        for i, seg in enumerate(analyses, start=1):
            data = seg.data
            if "_error" in data:
                shots.append(fallback_shot(i, seg.start, seg.end))
                continue
            move = str(data.get("camera_move", "static")).lower()
            framing = str(data.get("framing", "MS")).upper()
            shots.append(Shot(
                index=i,
                duration=seg.duration,
                framing=framing if framing in FRAMINGS else "MS",
                camera_move=move if move in CAMERA_MOVES else "static",
                camera_speed=str(data.get("camera_speed", "medium")).lower(),
                lens_mm=int(_coerce_number(data.get("lens_mm", 35)) or 35),
                lighting=str(data.get("lighting", ""))[:80],
                palette=[str(p) for p in (data.get("palette") or [])][:4],
                subject=str(data.get("subject", ""))[:90],
                action=str(data.get("action", ""))[:110],
                setting=str(data.get("setting", ""))[:90],
                cut_type=str(data.get("cut_out", "hard")).lower(),
                energy=int(_coerce_number(data.get("energy", 3)) or 3),
                notes=str(data.get("notes", ""))[:120],
            ))

        rhythm = compute_rhythm(shots)
        sheet = BeatSheet(title=title or Path(video).stem,
                          logline=f"reversed from {Path(video).name}",
                          aspect_ratio=_ratio_from(info),
                          target_duration=round(info["duration"], 2),
                          source="reverse", shots=shots)
        sheet.visual_style = _style_from(shots)
        return sheet


def _ratio_from(info: dict) -> str:
    width, height = info.get("width") or 0, info.get("height") or 0
    if not width or not height:
        return "16:9"
    ratio = width / height
    for label, value in (("9:16", 0.5625), ("16:9", 1.777), ("1:1", 1.0),
                         ("4:5", 0.8), ("21:9", 2.333)):
        if abs(ratio - value) < 0.08:
            return label
    return "16:9"


def _style_from(shots: list[Shot]) -> str:
    lights = [s.lighting for s in shots if s.lighting]
    palettes = [p for s in shots for p in s.palette]
    uniq = list(dict.fromkeys(palettes))[:5]
    style = []
    if lights:
        style.append(lights[0])
    if uniq:
        style.append("palette: " + "/".join(uniq))
    moves = sorted({s.camera_move for s in shots})
    style.append("move vocabulary: " + ", ".join(moves[:4]))
    return ", ".join(style)


def beat_sheet_brief(sheet: BeatSheet) -> str:
    """Human/VLM-readable summary used by the planner and by the CLI report."""
    rhythm = sheet.rhythm
    lines = [
        f"{len(sheet.shots)} shots / "
        f"{sheet.total_duration}s / {rhythm.cuts_per_30s} cuts per 30s / "
        f"acceleration {rhythm.acceleration}",
        f"move mix: {rhythm.move_mix}",
        f"energy curve: {rhythm.energy_curve}",
    ]
    for shot in sheet.shots:
        lines.append(
            f"  {shot.index:02d} {shot.duration:>4.1f}s {shot.framing:<7} "
            f"{shot.camera_move:<10} E{shot.energy} — {shot.subject or '-'} | {shot.action or '-'}"
        )
    return "\n".join(lines)
