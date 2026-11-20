"""Layer C — VLM gatekeeper and closed-loop retry policy.

The gate is the part that turns a one-shot render into a *loop*: every rendered
shot is sampled at three timestamps, those frames plus the anchor still are
sent to a vision model with a strict rubric, and the resulting scores decide
ACCEPT / RETRY / ESCALATE.

Scores are 0-100 per axis; :func:`weighted_score` folds them into 0-1 with
identity weighted highest, because identity drift is the failure that viewers
notice first.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable

WEIGHTS = {"identity": 0.40, "wardrobe": 0.20, "palette": 0.15,
           "framing": 0.15, "motion": 0.10}

RUBRIC = """You are a continuity supervisor on an AI film. You get:
1) REFERENCE: the approved character still (identity source of truth).
2) FRAMES: three frames sampled from one rendered shot (start / middle / end),
   in chronological order.

Score each axis 0-100. Be harsh; 100 means indistinguishable from the reference.
- identity: same face, age, body, hair, distinguishing marks
- wardrobe: same clothing items, colours, fit, accessories
- palette: same colour grade / lighting mood as the reference
- framing: does the shot actually look like the intended framing
- motion: are the frames plausibly one continuous camera move (no cuts, no jumps)

Return ONLY JSON:
{"identity":0-100,"wardrobe":0-100,"palette":0-100,"framing":0-100,
 "motion":0-100,"issues":["short issue",...],
 "verdict":"accept|retry|reject","notes":"one sentence"}
"""


@dataclass
class GateReport:
    identity: float = 0.0
    wardrobe: float = 0.0
    palette: float = 0.0
    framing: float = 0.0
    motion: float = 0.0
    issues: list[str] = field(default_factory=list)
    verdict: str = ""
    notes: str = ""
    raw: str = ""

    def to_dict(self) -> dict:
        return {"identity": self.identity, "wardrobe": self.wardrobe,
                "palette": self.palette, "framing": self.framing,
                "motion": self.motion, "issues": self.issues,
                "verdict": self.verdict, "notes": self.notes}


@dataclass
class GatePolicy:
    min_total: float = 0.82
    min_identity: float = 0.80
    max_retries: int = 2
    escalate_after: int = 2


@dataclass
class Decision:
    verdict: str            # accept | retry | escalate
    score: float
    reasons: list[str]
    actions: list[str]

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "score": round(self.score, 3),
                "reasons": self.reasons, "actions": self.actions}


def _coerce_number(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            return float(match.group())
    return 0.0


def parse_report(text: str) -> GateReport:
    """Extract the JSON rubric block from a model reply, tolerantly."""
    text = text or ""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"gate reply had no JSON object: {text[:160]!r}")
    blob = text[start:end + 1]
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        blob2 = re.sub(r",\s*}", "}", blob)
        data = json.loads(blob2)
    report = GateReport(raw=text)
    for axis in WEIGHTS:
        setattr(report, axis, max(0.0, min(100.0, _coerce_number(data.get(axis)))))
    issues = data.get("issues") or []
    report.issues = [str(i) for i in issues][:8]
    report.verdict = str(data.get("verdict", "")).lower()
    report.notes = str(data.get("notes", ""))[:300]
    return report


def weighted_score(report: GateReport) -> float:
    total = sum(WEIGHTS[k] * getattr(report, k) for k in WEIGHTS)
    return round(total / 100.0, 4)


def decision_actions(report: GateReport, score: float,
                     policy: GatePolicy) -> list[str]:
    actions: list[str] = []
    if report.identity / 100.0 < policy.min_identity:
        actions.append("re-anchor: regenerate the still from the master anchor and rebuild the chain")
        actions.append("raise cfg_scale to 0.7 so the video model hugs the frame")
    if report.wardrobe < 70:
        actions.append("inject the wardrobe clause verbatim into the image prompt")
    if report.palette < 70:
        actions.append("pin the colour grade in the image prompt (palette tokens) and keep motion prompt colour-free")
    if report.framing < 70:
        actions.append("rebuild framing: state lens + framing explicitly in the still, not the motion prompt")
    if report.motion < 70:
        actions.append("shorten the shot by 1-2s and simplify to a single camera move")
    if score < policy.min_total and not actions:
        actions.append("regenerate with a new seed")
    return list(dict.fromkeys(actions))


def decide(report: GateReport, policy: GatePolicy = GatePolicy(),
           attempt: int = 0) -> Decision:
    score = weighted_score(report)
    reasons: list[str] = []
    if report.identity / 100.0 < policy.min_identity:
        reasons.append(f"identity {report.identity:.0f} < {policy.min_identity * 100:.0f}")
    if score < policy.min_total:
        reasons.append(f"weighted {score:.2f} < {policy.min_total:.2f}")
    if report.verdict in ("reject", "retry") and not reasons:
        reasons.append(f"model verdict: {report.verdict}")

    if not reasons:
        return Decision("accept", score, ["all axes above threshold"], [])

    actions = decision_actions(report, score, policy)
    if attempt >= policy.max_retries:
        return Decision("escalate", score, reasons + ["retry budget exhausted"], actions)
    return Decision("retry", score, reasons, actions)


def gate_messages(reference_image: str, frame_images: Iterable[str],
                  shot_note: str = "", motion_prompt: str = "") -> list[dict]:
    """Build the chat payload; image paths are turned into data URIs upstream."""
    from .providers import image_content  # local import keeps module import-light

    frames = list(frame_images)[:4]
    parts: list[dict] = [{"type": "text", "text": RUBRIC}]
    parts.append({"type": "text", "text": f"REFERENCE (approved identity): {shot_note or 'anchor'}"})
    parts.append(image_content(reference_image))
    parts.append({"type": "text", "text": "FRAMES (start / middle / end of the shot):"})
    for frame in frames:
        parts.append(image_content(frame))
    if motion_prompt:
        parts.append({"type": "text", "text": f"Intended motion prompt: {motion_prompt}"})
    parts.append({"type": "text", "text": "Return the JSON rubric only."})
    return [{"role": "user", "content": parts}]


def summarise(reports: list[GateReport]) -> dict:
    if not reports:
        return {"shots": 0, "avg_score": 0.0, "worst_axis": None}
    totals = [weighted_score(r) for r in reports]
    axes = {k: sum(getattr(r, k) for r in reports) / len(reports) for k in WEIGHTS}
    worst = min(WEIGHTS, key=lambda axis: axes[axis])
    return {
        "shots": len(reports),
        "avg_score": round(sum(totals) / len(totals), 3),
        "min_score": round(min(totals), 3),
        "worst_axis": worst,
        "axes": {k: round(v, 1) for k, v in axes.items()},
    }
