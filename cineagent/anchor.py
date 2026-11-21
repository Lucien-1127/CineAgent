"""Layer B — character anchor + first/last-frame chaining.

Two failure modes this fixes:

1. **Identity drift across shots.** Every still used to be generated from a
   slightly different description, so the character slowly changed. Now one
   :class:`CharacterAnchor` produces a canonical identity block that is copied
   verbatim into every prompt, and one master still is generated once and
   re-used as the visual reference.

2. **Unlocked seams between shots.** Kling supports a first frame *and* a last
   frame. The chain planner makes shot *k*'s last frame the **same file** as
   shot *k+1*'s first frame, so the seam is pixel-identical by construction
   instead of "hopefully similar".

Chain modes
-----------
``bridge``  Pre-generate one still per shot; shot k runs first=B_k,
            last=B_(k+1). Deterministic, no drift, costs one still per shot.
``carry``   Render shot 1 from B_1, extract its final frame with ffmpeg, feed
            it as shot 2's first frame (legacy behaviour, no last-frame lock).
``loop``    Like ``bridge`` but the final shot closes back on B_1 so the clip
            can be looped.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from .beatsheet import BeatSheet, Shot
from .prompts import anchor_line

CHAIN_MODES = ("bridge", "carry", "loop")


@dataclass
class CharacterAnchor:
    anchor_id: str
    name: str
    canonical: str                 # <= 45 words, copied verbatim into prompts
    wardrobe: str = ""
    distinguishing: str = ""
    palette: list[str] = field(default_factory=list)
    seed: int = 0
    reference_image: str = ""      # path to the master still
    reference_hash: str = ""

    def identity_block(self) -> str:
        parts = [self.canonical]
        if self.wardrobe:
            parts.append(f"always wears {self.wardrobe}")
        if self.distinguishing:
            parts.append(self.distinguishing)
        if self.palette:
            parts.append("signature palette " + "/".join(self.palette[:3]))
        return "; ".join(p.strip(" .;") for p in parts if p)

    def prompt_line(self) -> str:
        return anchor_line(self.anchor_id, self.identity_block())

    def master_prompt(self, style: str = "") -> str:
        return ", ".join(x for x in (
            self.prompt_line(), "full-body character reference, neutral stance",
            "even studio lighting, clean background", style,
        ) if x)

    def stamp_reference(self, path: str | Path) -> None:
        path = Path(path)
        self.reference_image = str(path)
        if path.exists():
            self.reference_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]

    def matches_reference(self, path: str | Path) -> bool:
        path = Path(path)
        if not path.exists() or not self.reference_hash:
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16] == self.reference_hash


@dataclass
class AnchorSheet:
    anchors: dict[str, CharacterAnchor] = field(default_factory=dict)
    visual_style: str = ""
    negative_prompt: str = ""

    def add(self, anchor: CharacterAnchor) -> CharacterAnchor:
        self.anchors[anchor.anchor_id] = anchor
        return anchor

    def primary(self) -> CharacterAnchor:
        if not self.anchors:
            raise KeyError("anchor sheet is empty")
        return next(iter(self.anchors.values()))

    def get(self, anchor_id: str) -> CharacterAnchor:
        if anchor_id in self.anchors:
            return self.anchors[anchor_id]
        return self.primary()

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"visual_style": self.visual_style,
                "negative_prompt": self.negative_prompt,
                "anchors": {k: asdict(v) for k, v in self.anchors.items()}}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "AnchorSheet":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        sheet = cls(visual_style=data.get("visual_style", ""),
                    negative_prompt=data.get("negative_prompt", ""))
        for key, raw in (data.get("anchors") or {}).items():
            sheet.anchors[key] = CharacterAnchor(**raw)
        return sheet


@dataclass
class ShotChain:
    shot_index: int
    first_frame: str          # path or empty (text-to-video)
    last_frame: str
    mode: str = "bridge"
    rationale: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def plan_chain(beat: BeatSheet, mode: str = "bridge",
               still_paths: Iterable[str] | None = None,
               anchor_still: str = "") -> list[ShotChain]:
    """Build the first/last-frame plan for every shot.

    ``still_paths`` is the per-shot bridge stills (one per shot). For ``loop``
    an extra closing still is expected at index len(shots); if missing, the
    anchor still is used so the clip still resolves.
    """
    if mode not in CHAIN_MODES:
        raise ValueError(f"unknown chain mode {mode}; expected one of {CHAIN_MODES}")
    stills = list(still_paths or [])
    shots: list[Shot] = beat.shots
    chains: list[ShotChain] = []

    for i, shot in enumerate(shots):
        if mode == "carry":
            first = stills[i] if i < len(stills) else (anchor_still if i == 0 else "")
            chains.append(ShotChain(shot.index, first, "",
                                    mode, "carry mode: no last-frame lock"))
            continue

        first = stills[i] if i < len(stills) else ""
        if i + 1 < len(stills):
            last = stills[i + 1]
            why = f"last frame = still of shot {i + 2} (pixel-identical seam)"
        elif mode == "loop" and len(stills) >= len(shots):
            last = stills[0]
            why = "closing shot returns to the opening still (loopable)"
        elif anchor_still:
            last = anchor_still
            why = "final shot resolves on the character anchor still"
        else:
            last = ""
            why = "no closing frame available"
        chains.append(ShotChain(shot.index, first, last, mode, why))
    return chains


def verify_chain(chains: list[ShotChain]) -> list[str]:
    """Continuity invariants. Empty list means the seams are locked."""
    problems: list[str] = []
    if not chains:
        return ["empty chain"]
    last_index = len(chains)
    for chain in chains:
        if chain.last_frame and not chain.first_frame:
            problems.append(f"shot {chain.shot_index}: last frame without first frame")
    for prev, cur in zip(chains, chains[1:]):
        if prev.mode == "carry":
            if prev.last_frame:
                problems.append(f"shot {prev.shot_index}: carry mode must not set last frame")
            continue
        if prev.last_frame and cur.first_frame and prev.last_frame != cur.first_frame:
            problems.append(
                f"seam {prev.shot_index}→{cur.shot_index}: "
                f"{Path(prev.last_frame).name} != {Path(cur.first_frame).name}"
            )
        if not prev.last_frame and prev.shot_index < last_index:
            problems.append(f"shot {prev.shot_index}: missing last frame, seam unlocked")
    return problems


def seam_report(chains: list[ShotChain]) -> dict:
    locked = sum(1 for c in chains if c.last_frame and c.first_frame)
    # A seam exists between k and k+1; the final shot needs no closing frame.
    unlocked = [c.shot_index for c in chains[1:] if not c.first_frame]
    return {
        "shots": len(chains),
        "locked_seams": max(0, locked - 1),
        "unlocked": unlocked,
        "problems": verify_chain(chains),
    }
