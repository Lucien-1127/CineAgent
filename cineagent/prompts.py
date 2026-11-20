"""Prompt separation: static composition vs motion only.

The original pipeline's biggest visual failure was mixing everything into one
prompt: "wearing a red coat, neon alley, slow dolly in, rain" sent to both the
image model and the video model. The image model then hallucinated motion, and
the video model re-drew the character because the prompt re-described her in
slightly different words.

Rules enforced here:

* ``image_prompt`` describes **what is in the frame** (identity, wardrobe,
  setting, framing, lens, light, palette). Motion words are rejected.
* ``motion_prompt`` describes **how the frame changes** (camera move, speed,
  subject action, end state). Static descriptors are rejected — those are the
  image's job, and repeating them invites the video model to re-render them.
* The character anchor line is injected **verbatim** into every image prompt
  as ``[CHAR:id]`` so identity tokens never drift between shots.
"""

from __future__ import annotations

import re
from typing import Iterable

from .beatsheet import Shot

ANCHOR_RE = re.compile(r"\[CHAR:([A-Za-z0-9_-]+)\]")

MOTION_WORDS = (
    "dolly", "pan", "tilt", "truck", "crane", "orbit", "zoom", "handheld",
    "tracking", "push in", "pull out", "whip", "shake", "camera moves",
    "moves toward", "moves away", "accelerat", "slow motion", "time-lapse",
)

STATIC_WORDS = (
    "wearing", "wears", "dressed", "wardrobe", "scar", "tattoo",
    "lighting", "backlight", "key light", "palette", "teal and orange",
    "background", "architecture", "facade", "street", "interior", "costume",
    "makeup", "framing", "close-up", "wide shot", "medium shot", "lens",
    "film grain",
)

FRAMING_PHRASES = {
    "ECU": "extreme close-up",
    "CU": "close-up",
    "MCU": "medium close-up",
    "MS": "medium shot",
    "MWS": "medium wide shot",
    "WS": "wide shot",
    "EWS": "extreme wide shot",
    "OTS": "over-the-shoulder shot",
    "POV": "POV shot",
    "TWO-SHOT": "two-shot",
}

MOVE_PHRASES = {
    "static": "locked-off static frame",
    "pan-left": "steady pan to the left",
    "pan-right": "steady pan to the right",
    "tilt-up": "slow tilt up",
    "tilt-down": "slow tilt down",
    "dolly-in": "smooth dolly in",
    "dolly-out": "smooth dolly out",
    "truck-left": "lateral truck to the left",
    "truck-right": "lateral truck to the right",
    "crane-up": "crane up",
    "crane-down": "crane down",
    "handheld": "subtle handheld drift",
    "orbit": "half-orbit around the subject",
    "zoom-in": "slow zoom in",
    "zoom-out": "slow zoom out",
    "rack-focus": "rack focus to the background",
    "whip-pan": "fast whip pan",
}

SPEED_PHRASES = {"slow": "at a deliberate pace", "medium": "at a natural pace",
                 "fast": "with urgent speed"}


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().rstrip(".,;"))


def _join(parts: Iterable[str]) -> str:
    return ", ".join(p for p in (_clean(x) for x in parts) if p)


def anchor_line(anchor_id: str, canonical: str) -> str:
    """Verbatim identity token + description reused across every shot."""
    return f"[CHAR:{anchor_id}] {canonical}"


def build_image_prompt(shot: Shot, anchor_id: str, anchor_canonical: str,
                       style: str = "", extra: Iterable[str] = ()) -> str:
    """Static composition only. No camera movement, no verbs of change."""
    framing = FRAMING_PHRASES.get(shot.framing, "medium shot")
    palette = " / ".join(shot.palette[:3]) if shot.palette else ""
    parts = [
        anchor_line(anchor_id, anchor_canonical),
        f"{shot.subject} {shot.action}" if shot.action and shot.action.endswith("ing") else shot.subject,
        f"in {shot.setting}" if shot.setting else "",
        framing,
        f"{shot.lens_mm}mm lens",
        shot.lighting,
        f"palette: {palette}" if palette else "",
        style,
        *extra,
    ]
    return _join(parts)


def build_motion_prompt(shot: Shot, duration: float | None = None,
                        end_state: str = "") -> str:
    """Camera + subject motion only — nothing that belongs to the still."""
    move = MOVE_PHRASES.get(shot.camera_move, "locked-off static frame")
    speed = SPEED_PHRASES.get(shot.camera_speed, "at a natural pace")
    duration = duration if duration is not None else shot.duration
    parts = [
        f"{move} {speed}",
        f"subject {shot.action}" if shot.action else "",
        f"energy level {shot.energy}/5",
        f"sustained for {duration:.1f}s with no cuts",
        end_state or "landing on a composition that matches the next still",
    ]
    return _join(parts)


def build_omni_prompt(motion_prompt: str, refs: Iterable[str] = ("image_1", "image_2")) -> str:
    """Omni-Video references frames inline as ``<<<image_1>>>``."""
    prefix = " then ".join(f"<<<{r}>>> stays on-model" for r in refs)
    return _join([prefix, motion_prompt])


def validate_split(image_prompt: str, motion_prompt: str) -> list[str]:
    """Return rule violations for a prompt pair (empty list = clean)."""
    problems: list[str] = []
    low_img = image_prompt.lower()
    low_mot = motion_prompt.lower()

    leaked = [w for w in MOTION_WORDS if w in low_img]
    if leaked:
        problems.append(f"image_prompt contains motion words: {leaked}")
    if not ANCHOR_RE.search(image_prompt):
        problems.append("image_prompt is missing the [CHAR:id] anchor token")

    static_leak = [w for w in STATIC_WORDS if w in low_mot]
    if static_leak:
        problems.append(f"motion_prompt re-describes static traits: {static_leak}")
    if not any(w in low_mot for w in MOTION_WORDS) and "static" not in low_mot:
        problems.append("motion_prompt has no camera language")
    if "s" not in low_mot and "sec" not in low_mot:
        problems.append("motion_prompt does not state a duration")
    if len(motion_prompt) > 480:
        problems.append("motion_prompt too long — keep it to camera + action only")
    return problems


def split_ratio(image_prompt: str, motion_prompt: str) -> float:
    """Share of the pair's tokens spent on the static half (sanity metric)."""
    i, m = len(image_prompt.split()), len(motion_prompt.split())
    return round(i / max(1, i + m), 3)


def negative_prompt(kind: str = "video") -> str:
    if kind == "image":
        return ("worst quality, low quality, blurry, extra fingers, deformed, "
                "watermark, text, logo, oversaturated, cartoon, cgi")
    return ("different character, face change, identity change, face morphing, "
            "wardrobe change, appearance drift, flickering, jump cut, "
            "teleportation, colour shift, duplicated frames, watermark, text")
