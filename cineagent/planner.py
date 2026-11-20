"""Narrative planner — the fix for "劇情太單調" (flat, repetitive stories).

Three mechanisms, in order of strength:

1. **Rhythm adoption.** If a reference beat sheet exists (Layer A), the planner
   keeps its measured durations, cut count, move mix and energy curve, and only
   invents new content inside that skeleton. Structure can't go flat because it
   was measured on real footage.
2. **Per-shot function + turn.** Every shot must declare a ``function`` (hook /
   orient / escalate / turn / payoff) and a ``turn`` — the thing that is
   different at the end of the shot. Two shots may not share the same
   function+turn combination, which kills "same beat repeated 5 times".
3. **Monotony audit + repair.** :func:`audit` scores repetition (identical
   framing runs, single move, flat energy, same-length shots) and the planner
   feeds the violations back to the model for one repair pass. If the model is
   unavailable, a deterministic skeleton from the rhythm table is used.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable

from .beatsheet import BeatSheet, Shot, compute_rhythm
from .gate import _coerce_number
from .providers import Chat

FUNCTIONS = ("hook", "orient", "escalate", "turn", "payoff")

PLANNER_SYSTEM = """You are a film director planning a shot list that must not
feel repetitive. Output JSON only.

Hard rules:
- Every shot has a DIFFERENT function: hook, orient, escalate, turn, payoff.
  Use each at most once unless shots > 5, then repeat only escalate.
- Every shot has a "turn": one concrete thing that changes during the shot
  (a reveal, a decision, an arrival, a loss, a reversal). No two turns may be
  the same idea restated.
- Shot durations must VARY: no two adjacent shots within 0.4s of each other,
  and the final third must be shorter than the first third (acceleration).
- Use at least 3 different camera moves across the piece; never repeat the same
  move twice in a row unless the move is "static" and it is the payoff.
- Energy (1-5) must form a curve, not a flat line: start <=3, peak at the turn,
  never more than one 5.
- Framing must change between adjacent shots.
- Total duration must equal the requested total (Kling allows 3-15s per shot).

Schema:
{"title":"...","logline":"...","style":"comma-separated visual style",
 "negative":"...","character":{"name":"...","canonical":"<=45 words identity",
 "wardrobe":"...","distinguishing":"...","palette":["hue","hue"]},
 "shots":[{"function":"hook","duration":4.0,"framing":"CU","camera_move":"dolly-in",
 "camera_speed":"slow","lens_mm":50,"lighting":"...","palette":["teal","amber"],
 "setting":"...","subject":"...","action":"...","turn":"...","energy":3,
 "cut_type":"hard"}]}
"""


@dataclass
class PlanResult:
    beat: BeatSheet
    character: dict
    style: str
    negative: str
    adopted_reference: bool = False
    repairs: int = 0
    variety_fixes: list[str] = field(default_factory=list)


# Action keywords → a move that actually serves the action. Used only when the
# plan still reads flat after the model's own repair pass.
ACTION_MOVE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("走", "跑", "衝", "奔", "追", "上樓", "walk", "run", "chase", "sprint", "climb"), "handheld"),
    (("抬", "仰", "look up", "glance up", "raise the head"), "tilt-up"),
    (("低頭", "俯", "look down", "downward"), "tilt-down"),
    (("伸", "遞", "交", "拿", "reach", "hand over", "offer", "pick up"), "dolly-in"),
    (("轉", "回頭", "turn", "spin", "繞"), "orbit"),
    (("凝視", "眼神", "gaze", "stare", "認出", "識出"), "rack-focus"),
    (("雨", "rain", "風", "wind", "水", "water", "落下", "falling"), "truck-right"),
)

ROTATION = ("dolly-in", "handheld", "truck-right", "tilt-up", "orbit", "zoom-in", "dolly-out")
FRAMING_LADDER = ("ECU", "CU", "MCU", "MS", "MWS", "WS", "EWS")


def _hint_for(shot: Shot) -> str:
    blob = f"{shot.action} {shot.subject}".lower()
    for keywords, move in ACTION_MOVE_HINTS:
        if any(k in blob for k in keywords):
            return move
    return ""


def enforce_variety(beat: BeatSheet) -> list[str]:
    """Deterministic last resort: never ship a flat cut because the model froze.

    Only touches shots whose move is ``static`` (plus adjacent-duplicate
    framings). Durations, order, subjects and turns are untouched.
    """
    shots = beat.shots
    if len(shots) < 3:
        return []
    fixes: list[str] = []

    moves = [s.camera_move for s in shots]
    static_heavy = moves.count("static") * 2 > len(moves)
    flat = len(set(moves)) < 3
    if static_heavy or flat:
        rotate = 0
        for i, shot in enumerate(shots):
            if shot.camera_move != "static":
                continue
            if i == 0:
                continue  # keep the opening frame calm
            candidate = _hint_for(shot) or ROTATION[rotate % len(ROTATION)]
            prev = shots[i - 1].camera_move
            if candidate == prev:
                rotate += 1
                candidate = ROTATION[rotate % len(ROTATION)]
            if candidate == prev:
                candidate = "tilt-up" if prev != "tilt-up" else "zoom-in"
            shot.camera_move = candidate
            shot.camera_speed = "slow" if shot.camera_speed == "slow" else "medium"
            fixes.append(f"shot {shot.index}: static → {candidate}")
            rotate += 1

    for i in range(1, len(shots)):
        if shots[i].framing == shots[i - 1].framing:
            current = FRAMING_LADDER.index(shots[i].framing)
            neighbours = [current - 1, current + 1, current + 2, current - 2]
            for cand in neighbours:
                if 0 <= cand < len(FRAMING_LADDER):
                    new = FRAMING_LADDER[cand]
                    if i + 1 >= len(shots) or shots[i + 1].framing != new:
                        if new != shots[i - 1].framing:
                            shots[i].framing = new
                            fixes.append(f"shot {shots[i].index}: framing "
                                         f"{FRAMING_LADDER[current]} → {new}")
                            break
    return fixes


def _strip_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"planner returned no JSON: {text[:200]!r}")
    blob = text[start:end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*}", "}", blob))


def audit(beat: BeatSheet) -> list[str]:
    """Monotony checks beyond BeatSheet.validate()."""
    problems: list[str] = list(beat.validate())
    shots = beat.shots
    if len(shots) < 2:
        return problems

    framings = [s.framing for s in shots]
    moves = [s.camera_move for s in shots]
    durations = [s.duration for s in shots]

    if len(set(framings)) < min(3, len(shots)):
        problems.append(f"only {len(set(framings))} distinct framings — cut will look samey")
    if len(set(moves)) < min(3, len(shots)):
        problems.append(f"only {len(set(moves))} distinct camera moves")
    for prev, cur in zip(moves, moves[1:]):
        if prev == cur and prev != "static":
            problems.append(f"repeated consecutive move '{prev}'")
            break
    run_len, longest_run, run_move = 1, 1, moves[0]
    for prev, cur in zip(moves, moves[1:]):
        run_len = run_len + 1 if cur == prev else 1
        if run_len > longest_run:
            longest_run, run_move = run_len, cur
    if longest_run >= 3:
        problems.append(f"'{run_move}' repeated {longest_run}x in a row — reads as one long shot")
    if moves.count("static") * 2 > len(moves):
        problems.append(f"{moves.count('static')}/{len(moves)} shots are static — motion will feel dead")
    for prev, cur in zip(framings, framings[1:]):
        if prev == cur:
            problems.append(f"repeated consecutive framing '{prev}'")
            break
    if max(durations) - min(durations) < 1.0:
        problems.append(f"shot lengths nearly identical ({min(durations)}–{max(durations)}s)")
    if len(shots) >= 4:
        third = max(1, len(shots) // 3)
        if sum(durations[-third:]) / third >= sum(durations[:third]) / third:
            problems.append("edit does not accelerate — final shots are not shorter")

    turns = [s.subject.strip().lower() + "|" + s.action.strip().lower() for s in shots]
    dupes = len(turns) - len(set(turns))
    if dupes:
        problems.append(f"{dupes} shot(s) repeat an identical subject+action")
    return list(dict.fromkeys(problems))


def _skeleton(brief: str, total: float, count: int) -> dict:
    """Deterministic 5-function skeleton — never flat, no model required."""
    count = max(2, count)
    functions = ["hook", "orient", "escalate", "turn", "payoff"]
    framings = ["CU", "MS", "MWS", "WS", "ECU", "OTS", "MS"]
    moves = ["dolly-in", "handheld", "truck-right", "orbit", "static", "tilt-up"]
    weights = [1.0 if i == 0 else (0.75 + 0.5 * (i / max(1, count - 1))) for i in range(count)]
    raw = [total * w / sum(weights) for w in weights]
    durations = [max(3.0, min(15.0, round(d, 1))) for d in raw]
    scale = total / sum(durations)
    durations = [round(max(3.0, min(15.0, d * scale)), 1) for d in durations]

    shots = []
    for i in range(count):
        func = functions[i] if i < len(functions) else "escalate"
        shots.append({
            "function": func,
            "duration": durations[i],
            "framing": framings[i % len(framings)],
            "camera_move": moves[i % len(moves)],
            "camera_speed": "slow" if i == 0 else ("fast" if func in ("turn", "escalate") else "medium"),
            "lens_mm": [24, 35, 50, 85, 35][i % 5],
            "lighting": "",
            "palette": [],
            "setting": brief,
            "subject": brief,
            "action": f"{func}: {brief}",
            "turn": f"new information revealed at the end of shot {i + 1}",
            "energy": [2, 3, 4, 5, 3][i % 5] if count > 3 else 3,
            "cut_type": "hard",
        })
    return {"title": brief[:60], "logline": brief, "style": "", "negative": "",
            "character": {}, "shots": shots}


def adopt_rhythm(reference: BeatSheet, total: float | None = None,
                 count: int | None = None) -> dict:
    """Use the reference's measured durations/moves/framings as the skeleton."""
    ref = reference.shots
    if count and count != len(ref):
        # resample the reference rhythm onto the requested shot count
        idx = [round(i * (len(ref) - 1) / max(1, count - 1)) for i in range(count)]
        ref = [reference.shots[i] for i in idx]
    durations = [s.duration for s in ref]
    if total:
        scale = total / sum(durations)
        durations = [round(max(3.0, min(15.0, d * scale)), 1) for d in durations]
    shots = []
    for i, s in enumerate(ref):
        shots.append({
            "function": FUNCTIONS[i] if i < len(FUNCTIONS) else "escalate",
            "duration": durations[i],
            "framing": s.framing,
            "camera_move": s.camera_move,
            "camera_speed": s.camera_speed,
            "lens_mm": s.lens_mm,
            "lighting": s.lighting,
            "palette": s.palette,
            "setting": s.setting,
            "subject": s.subject,
            "action": s.action,
            "turn": s.notes or "state changes",
            "energy": s.energy,
            "cut_type": s.cut_type,
        })
    return {"title": reference.title, "logline": reference.logline,
            "style": reference.visual_style, "negative": reference.negative_prompt,
            "character": {}, "shots": shots}


class Planner:
    def __init__(self, chat: Chat | None):
        self.chat = chat

    def plan(self, brief: str, *, total: float = 30.0, shot_count: int = 5,
             aspect_ratio: str = "16:9", style: str = "",
             reference: BeatSheet | None = None,
             character_hint: str = "") -> PlanResult:
        adopted = reference is not None
        if reference is not None:
            skeleton = adopt_rhythm(reference, total=total, count=shot_count)
            instruction = (
                "Reuse this measured skeleton EXACTLY (durations, framings, moves, "
                "speeds, energy) and invent new subject/action/turn content that fits "
                "the brief:\n" + json.dumps(skeleton, ensure_ascii=False)
            )
        else:
            skeleton = _skeleton(brief, total, shot_count)
            instruction = (
                f"Plan {shot_count} shots totalling {total}s for this brief: {brief}\n"
                f"Aspect ratio: {aspect_ratio}"
            )
        if style:
            instruction += f"\nVisual style to keep consistent: {style}"
        if character_hint:
            instruction += f"\nCharacter to lock: {character_hint}"

        data = None
        if self.chat is not None:
            data = self._ask(instruction)
        if data is None:
            data = skeleton

        beat, character, style_out, negative = self._to_beat(data, brief, total,
                                                              aspect_ratio, style,
                                                              reference)
        repairs = 0
        problems = audit(beat)
        while problems and self.chat is not None and repairs < 2:
            repairs += 1
            fix_prompt = (
                instruction
                + "\n\nYour previous plan had these problems:\n- "
                + "\n- ".join(problems)
                + "\n\nReturn a corrected plan as JSON only (same schema)."
            )
            fixed = self._ask(fix_prompt)
            if fixed is None:
                break
            beat, character, style_out, negative = self._to_beat(
                fixed, brief, total, aspect_ratio, style, reference)
            problems = audit(beat)

        fixes = enforce_variety(beat)
        return PlanResult(beat=beat, character=character, style=style_out,
                          negative=negative, adopted_reference=adopted,
                          repairs=repairs, variety_fixes=fixes)

    def _ask(self, instruction: str) -> dict | None:
        if self.chat is None:
            return None
        try:
            text = self.chat.complete(
                [{"role": "system", "content": PLANNER_SYSTEM},
                 {"role": "user", "content": instruction}],
                temperature=0.75, max_tokens=3000, json_mode=True,
            )
            return _strip_json(text)
        except Exception:
            return None

    def _to_beat(self, data: dict, brief: str, total: float, aspect: str,
                 style: str, reference: BeatSheet | None
                 ) -> tuple[BeatSheet, dict, str, str]:
        shots: list[Shot] = []
        for i, raw in enumerate(data.get("shots", []), start=1):
            duration = float(_coerce_number(raw.get("duration", 5)) or 5)
            shots.append(Shot(
                index=i,
                duration=max(3.0, min(15.0, duration)),
                framing=str(raw.get("framing", "MS")).upper(),
                camera_move=str(raw.get("camera_move", "static")).lower(),
                camera_speed=str(raw.get("camera_speed", "medium")).lower(),
                lens_mm=int(_coerce_number(raw.get("lens_mm", 35)) or 35),
                lighting=str(raw.get("lighting", ""))[:90],
                palette=[str(p) for p in (raw.get("palette") or [])][:4],
                subject=str(raw.get("subject", ""))[:110],
                action=str(raw.get("action", ""))[:140],
                setting=str(raw.get("setting", ""))[:110],
                cut_type=str(raw.get("cut_type", "hard")).lower(),
                energy=int(_coerce_number(raw.get("energy", 3)) or 3),
                notes=str(raw.get("turn", ""))[:140],
            ))
        if not shots:
            shots = [Shot.from_dict(s) for s in _skeleton(brief, total, 4)["shots"]]

        # normalise total to the request (proportional, respecting 3-15s)
        current = sum(s.duration for s in shots)
        if current and abs(current - total) > 0.6:
            scale = total / current
            for shot in shots:
                shot.duration = round(max(3.0, min(15.0, shot.duration * scale)), 1)

        style_out = str(data.get("style", "") or style or
                        (reference.visual_style if reference else ""))
        negative = str(data.get("negative", "") or
                       (reference.negative_prompt if reference else ""))
        character = data.get("character") or {}
        sheet = BeatSheet(
            title=str(data.get("title", brief[:60])),
            logline=str(data.get("logline", brief)),
            aspect_ratio=aspect,
            target_duration=total,
            source="reverse" if reference is not None else "planned",
            shots=shots,
            visual_style=style_out,
            character_anchor=str((character or {}).get("canonical", "")),
            negative_prompt=negative,
        )
        return sheet, character, style_out, negative
