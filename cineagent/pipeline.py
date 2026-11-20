"""Pipeline orchestrator — the three layers wired into one closed loop.

    A  reverse (optional)  →  beat sheet with measured rhythm
    B  plan + anchor        →  character anchor, bridge stills, locked chain
    C  render + gate        →  VLM rubric per shot, retry with targeted fixes

Outputs under ``output/<run_id>/``:

    plan.json  anchor.json  chain.json  prompts.jsonl
    stills/*.jpg  shots/*.mp4  frames/*.jpg  report.json  SUMMARY.txt
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import gate as gate_mod
from . import media, prompts, reverse
from .anchor import CharacterAnchor, AnchorSheet, plan_chain, seam_report, verify_chain
from .beatsheet import BeatSheet
from .planner import Planner, PlanResult, audit
from .providers import Chat, MultiImages, OpenRouterVideo, OrcaVideo, ProviderError
from .routing import Router, RoutingError, snap_duration


@dataclass
class Config:
    outdir: Path = Path("output")
    aspect_ratio: str = "16:9"
    chain_mode: str = "bridge"
    video_tier: str = "best"
    image_tier: str = "best"
    vlm_tier: str = "balanced"
    llm_tier: str = "balanced"
    gate: gate_mod.GatePolicy = field(default_factory=gate_mod.GatePolicy)
    dry_run: bool = False
    live: bool = False          # dry_run but still call the real LLM (planning mode)
    reference_video: str = ""
    anchor_image: str = ""
    seed: int = 0


class Pipeline:
    def __init__(self, config: Config | None = None, router: Router | None = None):
        self.cfg = config or Config()
        self.router = router or Router()
        self._vlm: Chat | None = None
        self._images: OrcaImages | None = None

    # ── clients ──────────────────────────────────────────────────────────────
    def vlm(self) -> Chat:
        if self._vlm is None:
            d = self.router.resolve("vlm", self.cfg.vlm_tier)
            self._vlm = Chat(d.base_url, d.api_key, d.spec.id)
        return self._vlm

    def llm(self) -> Chat:
        d = self.router.resolve("llm", self.cfg.llm_tier)
        return Chat(d.base_url, d.api_key, d.spec.id)

    def images(self) -> MultiImages:
        if self._images is None:
            self._images = MultiImages(self.router.resolve_all("image", self.cfg.image_tier))
        return self._images

    def video_client(self):
        d = self.router.resolve("video", self.cfg.video_tier)
        if d.spec.provider == "openrouter":
            return OpenRouterVideo(d.base_url, d.api_key, d.spec.id), d.spec
        return OrcaVideo(d.base_url, d.api_key, d.spec.id), d.spec

    # ── stage A ──────────────────────────────────────────────────────────────
    def reverse_reference(self) -> BeatSheet | None:
        if not self.cfg.reference_video:
            return None
        ok, _ = media.available()
        if not ok:
            raise media.MediaError("ffmpeg/ffprobe not found — cannot reverse a reference video")
        engine = reverse.ReverseEngine(self.vlm(), workdir=self.cfg.outdir / "_reference")
        sheet = engine.analyse(self.cfg.reference_video)
        return sheet

    # ── stage B ──────────────────────────────────────────────────────────────
    def plan(self, brief: str, *, duration: float, shots: int, style: str = "",
             reference: BeatSheet | None = None,
             character_hint: str = "") -> tuple[PlanResult, AnchorSheet]:
        planner = Planner(None if (self.cfg.dry_run and not self.cfg.live) else self.llm())
        result = planner.plan(brief, total=duration, shot_count=shots,
                              aspect_ratio=self.cfg.aspect_ratio, style=style,
                              reference=reference, character_hint=character_hint)
        result.beat.visual_style = result.style or result.beat.visual_style
        result.beat.negative_prompt = result.negative or prompts.negative_prompt("video")
        sheet = self._anchor_sheet(result)
        return result, sheet

    def _anchor_sheet(self, result: PlanResult) -> AnchorSheet:
        char = result.character or {}
        anchor = CharacterAnchor(
            anchor_id=str(char.get("id") or "lead"),
            name=str(char.get("name") or "Lead"),
            canonical=str(char.get("canonical") or result.beat.character_anchor
                          or "the protagonist, consistent appearance across every shot"),
            wardrobe=str(char.get("wardrobe") or ""),
            distinguishing=str(char.get("distinguishing") or ""),
            palette=[str(p) for p in (char.get("palette") or [])][:3]
            or [p for s in result.beat.shots for p in s.palette][:3],
            seed=self.cfg.seed,
        )
        sheet = AnchorSheet(visual_style=result.style,
                            negative_prompt=result.negative or prompts.negative_prompt("video"))
        sheet.add(anchor)
        return sheet

    def ensure_anchor_still(self, sheet: AnchorSheet, run_dir: Path) -> Path:
        anchor = sheet.primary()
        if self.cfg.anchor_image:
            anchor.stamp_reference(self.cfg.anchor_image)
            return Path(self.cfg.anchor_image)
        dest = run_dir / "stills" / "anchor.png"
        if self.cfg.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"DRY-RUN")
            return dest
        self.images().generate(anchor.master_prompt(sheet.visual_style), dest,
                               aspect_ratio=self.cfg.aspect_ratio,
                               negative_prompt=prompts.negative_prompt("image"))
        anchor.stamp_reference(dest)
        return dest

    def build_stills(self, beat: BeatSheet, sheet: AnchorSheet, run_dir: Path) -> list[str]:
        anchor = sheet.primary()
        if self.cfg.anchor_image and self.cfg.chain_mode == "carry":
            # No image model needed: start from the approved still and let each
            # rendered clip hand its final frame to the next shot.
            return [str(self.cfg.anchor_image)]
        paths: list[str] = []
        for shot in beat.shots:
            prompt = prompts.build_image_prompt(shot, anchor.anchor_id,
                                                anchor.identity_block(),
                                                beat.visual_style)
            problems = prompts.validate_split(prompt, "static frame held for 3.0s")
            if problems:
                print(f"  ⚠️  still {shot.index}: {problems}")
            dest = run_dir / "stills" / f"shot_{shot.index:02d}.png"
            if self.cfg.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"DRY-RUN")
            else:
                self.images().generate(prompt, dest, aspect_ratio=self.cfg.aspect_ratio,
                                       negative_prompt=prompts.negative_prompt("image"))
            paths.append(str(dest))
        return paths

    # ── stage C ──────────────────────────────────────────────────────────────
    def gate_shot(self, video: Path, reference: Path, shot_duration: float,
                  motion_prompt: str, workdir: Path) -> tuple[gate_mod.Decision, gate_mod.GateReport | None]:
        if self.cfg.dry_run:
            return gate_mod.Decision("accept", 1.0, ["dry-run"], []), None
        times = [0.2, shot_duration / 2, max(0.3, shot_duration - 0.2)]
        frames = [str(p) for p in media.sample_frames(
            video, times, workdir / "frames", prefix=video.stem)]
        messages = gate_mod.gate_messages(str(reference), frames,
                                          shot_note=video.stem, motion_prompt=motion_prompt)
        try:
            reply = self.vlm().complete(messages, temperature=0.1, max_tokens=700, json_mode=True)
            report = gate_mod.parse_report(reply)
        except Exception as exc:
            print(f"     ⚠️  gate unavailable ({exc}) — accepting without verification")
            return gate_mod.Decision("accept", 0.0, [f"gate error: {exc}"], []), None
        return gate_mod.decide(report, self.cfg.gate, attempt=0), report

    def render_shot(self, shot, chain, beat: BeatSheet, sheet: AnchorSheet,
                    run_dir: Path, attempt: int = 0) -> Path:
        anchor = sheet.primary()
        motion = prompts.build_motion_prompt(shot)
        client, spec = self.video_client()
        dest = run_dir / "shots" / f"shot_{shot.index:02d}_a{attempt}.mp4"

        if self.cfg.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"DRY-RUN")
            return dest

        if isinstance(client, OpenRouterVideo):
            payload = client.build_payload(
                motion, duration=snap_duration(spec, shot.duration),
                aspect_ratio=self.cfg.aspect_ratio,
                first_frame=chain.first_frame or None,
                last_frame=chain.last_frame or None,
            )
        else:
            payload = client.build_payload(
                motion,
                first_frame=chain.first_frame or None,
                last_frame=chain.last_frame or None,
                aspect_ratio=self.cfg.aspect_ratio,
                duration=snap_duration(spec, shot.duration),
                mode="pro",
                negative_prompt=beat.negative_prompt or prompts.negative_prompt("video"),
                cfg_scale=0.7 if chain.last_frame else None,
            )
        payload["_model"] = spec.id
        return client.render(payload, dest, timeout=1200)

    def retry_adjust(self, shot, attempt: int, report: gate_mod.GateReport | None,
                     decision: gate_mod.Decision) -> None:
        """Apply targeted fixes in place before the next render attempt."""
        if report is None:
            shot.duration = max(3.0, round(shot.duration - 1.0, 1))
            return
        if report.motion < 70:
            shot.duration = max(3.0, round(shot.duration - 1.0, 1))
        if report.identity < 70:
            shot.camera_move = "static" if shot.camera_move != "static" else "dolly-in"
        if report.framing < 70:
            shot.lens_mm = 50 if shot.lens_mm != 50 else 35
        print(f"     ↻ retry {attempt + 1}: {decision.actions[:2]}")

    # ── full run ─────────────────────────────────────────────────────────────
    def run(self, brief: str, *, duration: float = 30.0, shots: int = 5,
            style: str = "", character_hint: str = "") -> dict:
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        run_dir = Path(self.cfg.outdir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        report: dict = {"run_id": run_id, "brief": brief, "dry_run": self.cfg.dry_run,
                        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

        # A
        reference = self.reverse_reference()
        if reference:
            reference.save(run_dir / "reference_beat_sheet.json")
            print(f"  🎞️  reference reversed: {reverse.beat_sheet_brief(reference)}")

        # B
        result, sheet = self.plan(brief, duration=duration, shots=shots, style=style,
                                  reference=reference, character_hint=character_hint)
        beat = result.beat
        problems = audit(beat)
        beat.save(run_dir / "plan.json")
        sheet.save(run_dir / "anchor.json")
        print(f"  🧭 plan: {len(beat.shots)} shots / {beat.total_duration}s / "
              f"repairs={result.repairs} / reference={result.adopted_reference}")
        if result.variety_fixes:
            print(f"  🔧 variety enforced: {result.variety_fixes}")
        print(f"     rhythm: {beat.rhythm.to_dict()}")
        if problems:
            print(f"  ⚠️  monotony audit: {problems}")

        anchor_still = self.ensure_anchor_still(sheet, run_dir)
        stills = self.build_stills(beat, sheet, run_dir)
        chains = plan_chain(beat, self.cfg.chain_mode, stills, str(anchor_still))
        seams = seam_report(chains)
        (run_dir / "chain.json").write_text(
            json.dumps({"mode": self.cfg.chain_mode,
                        "chains": [c.to_dict() for c in chains],
                        "seams": seams}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"  🔗 chain ({self.cfg.chain_mode}): {seams}")
        if seams["problems"]:
            print(f"  ⚠️  seam problems: {seams['problems']}")

        # prompts ledger
        anchor = sheet.primary()
        with (run_dir / "prompts.jsonl").open("w", encoding="utf-8") as fh:
            for shot in beat.shots:
                ip = prompts.build_image_prompt(shot, anchor.anchor_id, anchor.identity_block(),
                                                beat.visual_style)
                mp = prompts.build_motion_prompt(shot)
                fh.write(json.dumps({"shot": shot.index, "image_prompt": ip,
                                     "motion_prompt": mp,
                                     "violations": prompts.validate_split(ip, mp)},
                                    ensure_ascii=False) + "\n")

        # C
        shot_reports = []
        rendered: list[str] = []
        durations: dict[int, float] = {}
        for shot, chain in zip(beat.shots, chains):
            print(f"\n  🎬 shot {shot.index}: {shot.framing} {shot.camera_move} "
                  f"{shot.duration}s — {shot.action[:60]}")
            attempts, decision, report_obj, path = 0, None, None, None
            if self.cfg.chain_mode == "carry" and shot.index > 1 and rendered:
                try:
                    carry = media.extract_frame(
                        rendered[-1],
                        max(0.0, durations.get(shot.index - 1, shot.duration) - 0.15),
                        run_dir / "frames" / f"carry_{shot.index:02d}.jpg")
                    chain.first_frame = str(carry)
                    print(f"     🔗 carry: frame from shot {shot.index - 1} → first frame")
                except media.MediaError as exc:
                    print(f"     ⚠️  carry frame failed: {exc}")
            while attempts <= self.cfg.gate.max_retries:
                try:
                    path = self.render_shot(shot, chain, beat, sheet, run_dir, attempts)
                except (ProviderError, RoutingError) as exc:
                    print(f"     ❌ render failed: {exc}")
                    path = None
                    break
                decision, report_obj = self.gate_shot(
                    path, Path(chain.first_frame or anchor_still), shot.duration,
                    prompts.build_motion_prompt(shot), run_dir)
                print(f"     🔎 gate: {decision.verdict} {decision.score:.2f} "
                      f"{decision.reasons}")
                if decision.verdict == "accept":
                    break
                attempts += 1
                if decision.verdict == "escalate":
                    break
                self.retry_adjust(shot, attempts, report_obj, decision)

            if path and path.exists():
                rendered.append(str(path))
                try:
                    durations[shot.index] = media.probe(path)["duration"]
                except media.MediaError:
                    durations[shot.index] = shot.duration
            shot_reports.append({
                "shot": shot.index,
                "duration": shot.duration,
                "video": str(path) if path else "",
                "attempts": attempts,
                "decision": decision.to_dict() if decision else None,
                "gate": report_obj.to_dict() if report_obj else None,
                "chain": chain.to_dict(),
            })

        final = ""
        if rendered and not self.cfg.dry_run:
            try:
                out = media.concat(rendered, run_dir / "final.mp4")
                final = str(out)
                print(f"\n  ✅ final: {out}")
            except media.MediaError as exc:
                print(f"  ⚠️  concat failed: {exc}")

        report.update({
            "plan": beat.to_dict(),
            "audit": problems,
            "anchor": {"id": anchor.anchor_id, "still": str(anchor_still),
                       "hash": anchor.reference_hash},
            "chain_mode": self.cfg.chain_mode,
            "seams": seams,
            "shots": shot_reports,
            "gate_summary": gate_mod.summarise(
                [gate_mod.GateReport(**r["gate"]) for r in shot_reports if r["gate"]]
            ),
            "final": final,
            "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        (run_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "SUMMARY.txt").write_text(self.summary_text(report), encoding="utf-8")
        return report

    def summary_text(self, report: dict) -> str:
        lines = [f"CineAgent run {report['run_id']}",
                 f"brief: {report['brief']}",
                 f"shots: {len(report['plan']['shots'])} / "
                 f"{report['plan']['total_duration']}s",
                 f"chain: {report['chain_mode']} / seams: {report['seams']['locked_seams']} locked",
                 f"audit: {report['audit'] or 'clean'}",
                 f"gate: {report['gate_summary']}",
                 "", "shots:"]
        for row in report["shots"]:
            verdict = (row.get("decision") or {}).get("verdict", "n/a")
            score = (row.get("decision") or {}).get("score", 0)
            lines.append(f"  {row['shot']:02d} {row['duration']:>4.1f}s "
                         f"{verdict:<8} {score:.2f} attempts={row['attempts']}")
        lines.append("")
        lines.append(f"final: {report['final'] or '(none)'}")
        return "\n".join(lines)
