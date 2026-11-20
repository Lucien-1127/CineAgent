"""Beat sheet schema — the skeleton every downstream prompt is derived from.

A beat sheet is what Layer A (reverse engineering) extracts from a reference
video, and what the planner writes from scratch. Both paths produce the same
JSON so the rest of the pipeline never cares where it came from.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Iterable

FRAMINGS = ("ECU", "CU", "MCU", "MS", "MWS", "WS", "EWS", "OTS", "POV", "TWO-SHOT")
CAMERA_MOVES = (
    "static", "pan-left", "pan-right", "tilt-up", "tilt-down", "dolly-in",
    "dolly-out", "truck-left", "truck-right", "crane-up", "crane-down",
    "handheld", "orbit", "zoom-in", "zoom-out", "rack-focus", "whip-pan",
)
CUT_TYPES = ("hard", "match", "fade", "dissolve", "whip", "jump", "none")
SPEEDS = ("slow", "medium", "fast")

# Models drift constantly on enum spelling ("dolly in", "push-in", "tracking").
# Coercing those to "static" silently flattened whole cuts, so map them first.
MOVE_ALIASES = {
    "static": "static", "locked": "static", "locked-off": "static", "still": "static",
    "fixed": "static", "lock-off": "static", "no movement": "static",
    "pan": "pan-right", "pan left": "pan-left", "pan right": "pan-right",
    "pans left": "pan-left", "pans right": "pan-right",
    "tilt up": "tilt-up", "tilt down": "tilt-down", "tilt": "tilt-up",
    "dolly": "dolly-in", "dolly in": "dolly-in", "dolly out": "dolly-out",
    "push in": "dolly-in", "push-in": "dolly-in", "push": "dolly-in",
    "pull out": "dolly-out", "pull-out": "dolly-out", "pull back": "dolly-out",
    "tracking": "truck-right", "track": "truck-right", "truck": "truck-right",
    "truck left": "truck-left", "truck right": "truck-right",
    "follow": "handheld", "handheld": "handheld", "hand-held": "handheld",
    "shaky": "handheld", "steadicam": "handheld",
    "crane": "crane-up", "crane up": "crane-up", "crane down": "crane-down",
    "orbit": "orbit", "arc": "orbit", "circle": "orbit", "orbit around": "orbit",
    "zoom": "zoom-in", "zoom in": "zoom-in", "zoom out": "zoom-out",
    "rack focus": "rack-focus", "pull focus": "rack-focus",
    "whip pan": "whip-pan", "whip": "whip-pan",
}

FRAMING_ALIASES = {
    "extreme close-up": "ECU", "extreme close up": "ECU", "ecu": "ECU",
    "close-up": "CU", "close up": "CU", "closeup": "CU", "cu": "CU",
    "medium close-up": "MCU", "medium close up": "MCU", "mcu": "MCU",
    "medium": "MS", "medium shot": "MS", "ms": "MS",
    "medium wide": "MWS", "mws": "MWS",
    "wide": "WS", "wide shot": "WS", "full shot": "WS", "ws": "WS",
    "extreme wide": "EWS", "establishing": "EWS", "ews": "EWS",
    "over the shoulder": "OTS", "over-the-shoulder": "OTS", "ots": "OTS",
    "pov": "POV", "point of view": "POV",
    "two-shot": "TWO-SHOT", "two shot": "TWO-SHOT", "twoshot": "TWO-SHOT",
}


def normalise_move(raw: str) -> str:
    value = (raw or "").strip().lower().replace("_", "-")
    if value in CAMERA_MOVES:
        return value
    return MOVE_ALIASES.get(value, "static")


def normalise_framing(raw: str) -> str:
    value = (raw or "").strip().upper()
    if value in FRAMINGS:
        return value
    return FRAMING_ALIASES.get((raw or "").strip().lower().replace("_", "-"), "MS")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass
class Shot:
    index: int
    duration: float
    framing: str = "MS"
    camera_move: str = "static"
    camera_speed: str = "medium"
    lens_mm: int = 35
    lighting: str = ""
    palette: list[str] = field(default_factory=list)
    subject: str = ""
    action: str = ""
    setting: str = ""
    cut_type: str = "hard"
    energy: int = 3
    dialogue: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        self.duration = round(float(self.duration), 2)
        self.energy = int(_clamp(int(self.energy), 1, 5))
        self.framing = normalise_framing(self.framing)
        self.camera_move = normalise_move(self.camera_move)
        if self.camera_speed not in SPEEDS:
            self.camera_speed = "medium"
        if self.cut_type not in CUT_TYPES:
            self.cut_type = "hard"

    @property
    def start(self) -> float:
        return 0.0  # filled by BeatSheet when needed

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Shot":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class Rhythm:
    shot_count: int = 0
    total_duration: float = 0.0
    avg_shot: float = 0.0
    cuts_per_30s: float = 0.0
    shortest: float = 0.0
    longest: float = 0.0
    acceleration: float = 1.0
    energy_curve: list[int] = field(default_factory=list)
    move_mix: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def compute_rhythm(shots: Iterable[Shot]) -> Rhythm:
    """Derive pacing numbers used to keep a 30s cut from feeling flat.

    ``acceleration`` compares the mean shot length of the final third with the
    first third: >1 means the edit speeds up (the usual trailer/短影音 shape).
    """
    items = list(shots)
    if not items:
        return Rhythm()
    durations = [s.duration for s in items]
    total = sum(durations)
    third = max(1, len(items) // 3)
    head = mean(durations[:third]) or 0.01
    tail = mean(durations[-third:]) or 0.01
    moves: dict[str, int] = {}
    for shot in items:
        moves[shot.camera_move] = moves.get(shot.camera_move, 0) + 1
    return Rhythm(
        shot_count=len(items),
        total_duration=round(total, 2),
        avg_shot=round(mean(durations), 2),
        cuts_per_30s=round(len(items) * 30.0 / total, 2) if total else 0.0,
        shortest=round(min(durations), 2),
        longest=round(max(durations), 2),
        acceleration=round(head / tail, 2),
        energy_curve=[s.energy for s in items],
        move_mix=dict(sorted(moves.items(), key=lambda kv: -kv[1])),
    )


@dataclass
class BeatSheet:
    title: str = ""
    logline: str = ""
    aspect_ratio: str = "16:9"
    target_duration: float = 30.0
    source: str = "planned"          # planned | reverse
    shots: list[Shot] = field(default_factory=list)
    visual_style: str = ""
    character_anchor: str = ""
    negative_prompt: str = ""

    def __post_init__(self) -> None:
        self.shots = sorted(self.shots, key=lambda s: s.index)
        for i, shot in enumerate(self.shots, start=1):
            shot.index = i

    @property
    def rhythm(self) -> Rhythm:
        return compute_rhythm(self.shots)

    @property
    def total_duration(self) -> float:
        return round(sum(s.duration for s in self.shots), 2)

    def boundaries(self) -> list[tuple[float, float]]:
        out, cursor = [], 0.0
        for shot in self.shots:
            out.append((round(cursor, 2), round(cursor + shot.duration, 2)))
            cursor += shot.duration
        return out

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.shots:
            problems.append("beat sheet has no shots")
            return problems
        for shot in self.shots:
            if shot.duration <= 0:
                problems.append(f"shot {shot.index}: non-positive duration")
            if shot.duration > 15:
                problems.append(f"shot {shot.index}: {shot.duration}s exceeds Kling's 15s ceiling")
            if shot.duration < 3:
                problems.append(f"shot {shot.index}: {shot.duration}s below Kling's 3s floor")
        drift = abs(self.total_duration - self.target_duration)
        if drift > max(1.0, self.target_duration * 0.15):
            problems.append(
                f"total {self.total_duration}s drifts from target {self.target_duration}s"
            )
        energies = [s.energy for s in self.shots]
        if len(set(energies)) == 1 and len(energies) > 2:
            problems.append("flat energy curve — every shot has the same energy")
        if all(s.camera_move == "static" for s in self.shots) and len(self.shots) > 1:
            problems.append("no camera movement anywhere — motion will feel dead")
        return problems

    def to_dict(self) -> dict:
        data = asdict(self)
        data["rhythm"] = self.rhythm.to_dict()
        data["total_duration"] = self.total_duration
        data["boundaries"] = self.boundaries()
        return data

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: dict) -> "BeatSheet":
        shots = [Shot.from_dict(s) for s in data.get("shots", [])]
        allowed = {"title", "logline", "aspect_ratio", "target_duration", "source",
                   "visual_style", "character_anchor", "negative_prompt"}
        kwargs = {k: v for k, v in data.items() if k in allowed}
        return cls(shots=shots, **kwargs)

    @classmethod
    def load(cls, path: str | Path) -> "BeatSheet":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
