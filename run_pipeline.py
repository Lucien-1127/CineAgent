#!/usr/bin/env python3
"""CineAgent v4 CLI — three-layer closed loop.

    python3 run_pipeline.py doctor
    python3 run_pipeline.py reverse --video reference.mp4
    python3 run_pipeline.py plan   --brief "..." --duration 30 --shots 5
    python3 run_pipeline.py run    --brief "..." --duration 30 --shots 5
    python3 run_pipeline.py check  --plan output/<run>/plan.json

Layers:
    A  reverse.py   reference video → beat sheet (rhythm + shot skeleton)
    B  anchor.py    character anchor + first/last-frame chain
    C  gate.py      VLM rubric → accept / retry / escalate

No third-party runtime dependencies: stdlib for HTTP, ffmpeg for media.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from cineagent import media, prompts, reverse, routing
from cineagent.anchor import AnchorSheet, CharacterAnchor, plan_chain, seam_report
from cineagent.beatsheet import BeatSheet, Shot
from cineagent.pipeline import Config, Pipeline
from cineagent.planner import audit


def cmd_doctor(args: argparse.Namespace) -> int:
    routing.load_env()
    print("CineAgent doctor")
    print("=" * 60)

    ff, fp = media.available()
    print(f"ffmpeg:  {'ok' if ff else 'MISSING'}   ffprobe: {'ok' if fp else 'MISSING'}")
    print(f"python:  {sys.version.split()[0]}")

    for provider, envs in (("orcarouter", routing.ORCAROUTER_KEY_ENVS),
                           ("openrouter", routing.OPENROUTER_KEY_ENVS)):
        name, value = routing._first_env(envs)  # noqa: SLF001 - doctor reports presence only
        print(f"{provider:<11} key: {'set via ' + name if value else 'NOT SET'}"
              f"  (env: {', '.join(envs)})")

    router = routing.Router(refresh=args.refresh)
    report = router.report()
    for capability, rows in report.items():
        print(f"\n[{capability}]")
        for row in rows:
            mark = "ok  " if row["listed"] else "skip"
            flf = " FLF" if row["first_last_frame"] else ""
            print(f"  {mark} {row['model']:<34} {row['tier']:<9}{flf:<5} {row['detail']}")
    try:
        for capability in ("video", "image", "vlm", "llm"):
            decision = router.resolve(capability, "best")
            print(f"\nresolved {capability:<6} -> {decision.spec.provider}:{decision.spec.id}")
    except routing.RoutingError as exc:
        print(f"\nrouting error: {exc}")
        return 1
    return 0


def cmd_reverse(args: argparse.Namespace) -> int:
    routing.load_env()
    router = routing.Router()
    decision = router.resolve("vlm", args.vlm_tier)
    from cineagent.providers import Chat

    chat = Chat(decision.base_url, decision.api_key, decision.spec.id)
    engine = reverse.ReverseEngine(chat, threshold=args.threshold,
                                   max_shots=args.max_shots,
                                   workdir=Path(args.out).parent / "_reference")
    sheet = engine.analyse(args.video)
    out = Path(args.out)
    sheet.save(out)
    print(reverse.beat_sheet_brief(sheet))
    print(f"\nbeat sheet -> {out}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Offline verification of an existing plan: audit + prompt split + chain."""
    beat = BeatSheet.load(args.plan)
    problems = audit(beat)
    print(f"plan: {len(beat.shots)} shots / {beat.total_duration}s / "
          f"source={beat.source}")
    print(f"rhythm: {json.dumps(beat.rhythm.to_dict(), ensure_ascii=False)}")
    print(f"audit: {problems or 'clean'}")

    stills = [f"stills/shot_{s.index:02d}.png" for s in beat.shots]
    chains = plan_chain(beat, args.chain_mode, stills, "stills/anchor.png")
    seams = seam_report(chains)
    print(f"chain ({args.chain_mode}): {seams}")

    anchor_id, canonical = "lead", beat.character_anchor or "the protagonist"
    bad = 0
    for shot in beat.shots:
        ip = prompts.build_image_prompt(shot, anchor_id, canonical, beat.visual_style)
        mp = prompts.build_motion_prompt(shot)
        violations = prompts.validate_split(ip, mp)
        bad += len(violations)
        print(f"  {shot.index:02d} split={prompts.split_ratio(ip, mp)} "
              f"{'OK' if not violations else violations}")
    ok = not problems and not seams["problems"] and bad == 0
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_plan(args: argparse.Namespace) -> int:
    routing.load_env()
    cfg = Config(outdir=Path(args.out), aspect_ratio=args.aspect,
                 chain_mode=args.chain_mode, dry_run=True,
                 reference_video=args.reference or "",
                 anchor_image=args.anchor_image or "",
                 live=args.live)
    pipe = Pipeline(cfg)
    report = pipe.run(args.brief, duration=args.duration, shots=args.shots,
                      style=args.style or "", character_hint=args.character or "")
    print(pipe.summary_text(report))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    routing.load_env()
    cfg = Config(outdir=Path(args.out), aspect_ratio=args.aspect,
                 chain_mode=args.chain_mode, dry_run=args.dry_run,
                 video_tier=args.video_tier, image_tier=args.image_tier,
                 vlm_tier=args.vlm_tier, llm_tier=args.llm_tier,
                 reference_video=args.reference or "",
                 anchor_image=args.anchor_image or "")
    cfg.gate.max_retries = args.max_retries
    pipe = Pipeline(cfg)
    report = pipe.run(args.brief, duration=args.duration, shots=args.shots,
                      style=args.style or "", character_hint=args.character or "")
    print(pipe.summary_text(report))
    return 0 if report.get("accepted") or cfg.dry_run else 1


def cmd_smoke(args: argparse.Namespace) -> int:
    """Cheapest possible end-to-end proof: 1 still → 1 clip → VLM gate."""
    routing.load_env()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = Config(outdir=out, aspect_ratio=args.aspect, chain_mode="carry",
                 image_tier=args.image_tier, video_tier=args.video_tier,
                 vlm_tier=args.vlm_tier)
    pipe = Pipeline(cfg)

    anchor = CharacterAnchor(anchor_id="lead", name="Courier",
                             canonical="a 28-year-old courier in a red raincoat, "
                                       "close-cropped black hair, faint scar on the left brow",
                             wardrobe="red raincoat, scuffed boots",
                             palette=["teal", "amber"])
    sheet = AnchorSheet(visual_style="cinematic realism, teal and amber, film grain")
    sheet.add(anchor)
    shot = Shot(index=1, duration=float(args.duration), framing="MCU",
                camera_move="dolly-in", camera_speed="slow", lens_mm=50,
                lighting="hard neon from the left, wet reflections",
                palette=["teal", "amber"],
                subject="the courier holding a glowing parcel",
                action="lifts the parcel toward the light, rain streaking past",
                setting="rain-slicked alley at night", energy=3)
    beat = BeatSheet(title="smoke", target_duration=shot.duration, shots=[shot],
                     visual_style=sheet.visual_style,
                     character_anchor=anchor.canonical)

    print("1) anchor still …")
    still = pipe.ensure_anchor_still(sheet, out)
    print(f"   still: {still} ({still.stat().st_size // 1024}KB)")

    print("2) shot still …")
    stills = pipe.build_stills(beat, sheet, out)
    chains = plan_chain(beat, "carry", stills, str(still))
    print(f"   seams: {seam_report(chains)}")

    print("3) render …")
    video = pipe.render_shot(shot, chains[0], beat, sheet, out, 0)
    info = media.probe(video)
    print(f"   video: {video} ({info['duration']:.2f}s, {info['width']}x{info['height']})")

    print("4) gate …")
    decision, report = pipe.gate_shot(video, Path(still), shot.duration,
                                      prompts.build_motion_prompt(shot), out)
    print(f"   verdict: {decision.verdict} score={decision.score:.2f} reasons={decision.reasons}")
    if report:
        print(f"   axes: {report.to_dict()}")
    ok = video.exists() and info["duration"] > 0 and decision.verdict == "accept"
    print("\nSMOKE:", "PASS" if ok else "CHECK")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CineAgent v4 — locked, rhythm-aware video pipeline")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="check keys, models, ffmpeg")
    d.add_argument("--refresh", action="store_true", help="bypass model catalog cache")
    d.set_defaults(func=cmd_doctor)

    r = sub.add_parser("reverse", help="reverse a reference video into a beat sheet")
    r.add_argument("--video", required=True)
    r.add_argument("--out", default="output/reference_beat_sheet.json")
    r.add_argument("--threshold", type=float, default=0.30)
    r.add_argument("--max-shots", type=int, default=12)
    r.add_argument("--vlm-tier", default="balanced")
    r.set_defaults(func=cmd_reverse)

    c = sub.add_parser("check", help="offline audit of a plan (no API calls)")
    c.add_argument("--plan", required=True)
    c.add_argument("--chain-mode", default="bridge", choices=["bridge", "carry", "loop"])
    c.set_defaults(func=cmd_check)

    s = sub.add_parser("smoke", help="live 1-shot end-to-end proof (spends credit)")
    s.add_argument("--out", default="output/smoke")
    s.add_argument("--aspect", default="9:16")
    s.add_argument("--duration", type=float, default=5.0)
    s.add_argument("--image-tier", default="budget")
    s.add_argument("--video-tier", default="budget")
    s.add_argument("--vlm-tier", default="balanced")
    s.set_defaults(func=cmd_smoke)

    common = dict()
    for name, func, dry in (("plan", cmd_plan, True), ("run", cmd_run, False)):
        sp = sub.add_parser(name, help="plan only (dry)" if dry else "full render")
        sp.add_argument("--brief", required=True)
        sp.add_argument("--duration", type=float, default=30.0)
        sp.add_argument("--shots", type=int, default=5)
        sp.add_argument("--style", default="")
        sp.add_argument("--character", default="")
        sp.add_argument("--aspect", default="16:9", choices=list(media.ASPECTS))
        sp.add_argument("--out", default="output")
        sp.add_argument("--chain-mode", default="bridge", choices=["bridge", "carry", "loop"])
        sp.add_argument("--reference", default="", help="reference video to reverse first")
        sp.add_argument("--anchor-image", default="", help="pre-approved character still")
        sp.add_argument("--live", action="store_true", help="plan: use the real LLM")
        sp.add_argument("--video-tier", default="best")
        sp.add_argument("--image-tier", default="best")
        sp.add_argument("--vlm-tier", default="balanced")
        sp.add_argument("--llm-tier", default="balanced")
        sp.add_argument("--max-retries", type=int, default=2)
        sp.add_argument("--dry-run", action="store_true")
        sp.set_defaults(func=func, **common)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in ("plan", "run") and args.command == "plan":
        args.dry_run = True
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
