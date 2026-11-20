"""Offline tests — no network, no API keys, no ffmpeg required.

Covers the three closed-loop invariants the v4 rewrite exists to guarantee:

1. prompt separation (image = static, motion = movement only)
2. seam locking (last frame of shot k == first frame of shot k+1)
3. gate arithmetic + verdict policy
"""

from __future__ import annotations

import json
import unittest

from cineagent import gate, prompts, routing
from cineagent.anchor import CharacterAnchor, AnchorSheet, plan_chain, seam_report, verify_chain
from cineagent.beatsheet import BeatSheet, Shot
from cineagent.planner import Planner, _skeleton, audit, enforce_variety


def cast() -> list[Shot]:
    return [
        Shot(index=1, duration=4.5, framing="CU", camera_move="dolly-in", energy=2,
             subject="a courier", action="steps into the rain", setting="neon alley",
             lighting="hard neon from the left", palette=["teal", "amber"]),
        Shot(index=2, duration=6.0, framing="MS", camera_move="handheld", energy=3,
             subject="the courier", action="checks a glowing parcel", setting="neon alley",
             lighting="hard neon from the left", palette=["teal", "amber"]),
        Shot(index=3, duration=3.5, framing="WS", camera_move="crane-up", energy=5,
             subject="the alley", action="collapses into light", setting="neon alley",
             lighting="blown-out white", palette=["white", "teal"]),
    ]


def beat() -> BeatSheet:
    return BeatSheet(title="t", target_duration=14.0, shots=cast(),
                     visual_style="cinematic, teal and orange, film grain",
                     character_anchor="a 28-year-old courier in a red raincoat")


class PromptSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.anchor = CharacterAnchor(anchor_id="lead", name="Courier",
                                      canonical="a 28-year-old courier in a red raincoat",
                                      wardrobe="red raincoat, scuffed boots")

    def test_image_prompt_has_anchor_and_no_motion(self):
        shot = cast()[0]
        ip = prompts.build_image_prompt(shot, self.anchor.anchor_id,
                                        self.anchor.identity_block(), "cinematic")
        self.assertIn("[CHAR:lead]", ip)
        self.assertNotIn("dolly", ip.lower())
        self.assertNotIn("pan", ip.lower())

    def test_motion_prompt_has_camera_and_duration_only(self):
        mp = prompts.build_motion_prompt(cast()[0])
        self.assertIn("dolly in", mp.lower())
        self.assertIn("4.5s", mp)

    def test_validate_split_clean_pair(self):
        shot = cast()[0]
        ip = prompts.build_image_prompt(shot, self.anchor.anchor_id,
                                        self.anchor.identity_block())
        mp = prompts.build_motion_prompt(shot)
        self.assertEqual(prompts.validate_split(ip, mp), [])

    def test_validate_split_catches_leaks(self):
        problems = prompts.validate_split(
            "wide shot, camera pans left across the street", "slow dolly in over 4.0s")
        joined = " ".join(problems)
        self.assertIn("motion words", joined)
        self.assertIn("anchor token", joined)

    def test_static_description_leaking_into_motion_is_flagged(self):
        problems = prompts.validate_split(
            "[CHAR:lead] a courier", "she wears a red raincoat, dolly in, 4.0s")
        self.assertTrue(any("static traits" in p for p in problems))


class BeatSheetTests(unittest.TestCase):
    def test_rhythm_is_measured(self):
        rhythm = beat().rhythm
        self.assertEqual(rhythm.shot_count, 3)
        self.assertEqual(rhythm.total_duration, 14.0)
        self.assertGreater(rhythm.cuts_per_30s, 0)
        self.assertGreater(max(rhythm.energy_curve), min(rhythm.energy_curve))

    def test_flat_sheet_is_rejected(self):
        flat = BeatSheet(target_duration=12.0, shots=[
            Shot(index=i, duration=4.0, framing="MS", camera_move="static", energy=3)
            for i in range(1, 4)])
        problems = " ".join(flat.validate())
        self.assertIn("flat energy", problems)
        self.assertIn("no camera movement", problems)

    def test_duration_ceiling(self):
        sheet = BeatSheet(target_duration=20.0,
                          shots=[Shot(index=1, duration=20.0)])
        self.assertTrue(any("15s ceiling" in p for p in sheet.validate()))

    def test_roundtrip(self):
        original = beat()
        again = BeatSheet.from_dict(original.to_dict())
        self.assertEqual(again.total_duration, original.total_duration)
        self.assertEqual([s.index for s in again.shots], [1, 2, 3])


class ChainTests(unittest.TestCase):
    def test_bridge_chain_locks_every_seam(self):
        stills = ["stills/a.png", "stills/b.png", "stills/c.png"]
        chains = plan_chain(beat(), "bridge", stills, "stills/anchor.png")
        self.assertEqual(chains[0].first_frame, "stills/a.png")
        self.assertEqual(chains[0].last_frame, "stills/b.png")
        self.assertEqual(chains[0].last_frame, chains[1].first_frame)
        self.assertEqual(verify_chain(chains), [])
        self.assertEqual(seam_report(chains)["locked_seams"], 2)

    def test_loop_mode_closes_on_opening(self):
        stills = ["stills/a.png", "stills/b.png", "stills/c.png"]
        chains = plan_chain(beat(), "loop", stills, "stills/anchor.png")
        self.assertEqual(chains[-1].last_frame, "stills/a.png")

    def test_broken_chain_is_detected(self):
        chains = plan_chain(beat(), "bridge", ["a.png", "b.png"], "anchor.png")
        chains[1].first_frame = "wrong.png"
        problems = " ".join(verify_chain(chains))
        self.assertIn("seam", problems)

    def test_end_frame_without_first_is_invalid(self):
        from cineagent.providers import OrcaVideo, ProviderError
        client = OrcaVideo("https://example.invalid/v1", "k", "kling/kling-v3")
        with self.assertRaises(ProviderError):
            client.build_payload("move", first_frame=None, last_frame="last.png")

    def test_anchor_still_hash_detects_swap(self):
        anchor = CharacterAnchor(anchor_id="lead", name="x", canonical="y")
        self.assertFalse(anchor.matches_reference("nope.png"))


class GateTests(unittest.TestCase):
    def test_parse_fenced_json(self):
        reply = """```json
        {"identity": 92, "wardrobe": 88, "palette": 90, "framing": 80,
         "motion": 75, "issues": [], "verdict": "accept", "notes": "same person"}
        ```"""
        report = gate.parse_report(reply)
        self.assertEqual(report.identity, 92)
        self.assertEqual(gate.weighted_score(report), 0.874)

    def test_low_identity_forces_retry(self):
        report = gate.GateReport(identity=40, wardrobe=90, palette=90,
                                 framing=90, motion=90, verdict="reject")
        decision = gate.decide(report, gate.GatePolicy(), attempt=0)
        self.assertEqual(decision.verdict, "retry")
        self.assertTrue(any("re-anchor" in a for a in decision.actions))

    def test_exhausted_budget_escalates(self):
        report = gate.GateReport(identity=30, wardrobe=30, palette=30,
                                 framing=30, motion=30)
        decision = gate.decide(report, gate.GatePolicy(max_retries=2), attempt=2)
        self.assertEqual(decision.verdict, "escalate")

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(gate.WEIGHTS.values()), 1.0, places=6)

    def test_summary_reports_worst_axis(self):
        reports = [gate.GateReport(identity=90, wardrobe=60, palette=90,
                                   framing=90, motion=90)]
        self.assertEqual(gate.summarise(reports)["worst_axis"], "wardrobe")


class PlannerTests(unittest.TestCase):
    def test_skeleton_varies_structure(self):
        data = _skeleton("a courier in the rain", 30.0, 5)
        framings = {s["framing"] for s in data["shots"]}
        moves = {s["camera_move"] for s in data["shots"]}
        self.assertGreaterEqual(len(framings), 3)
        self.assertGreaterEqual(len(moves), 3)
        self.assertAlmostEqual(sum(s["duration"] for s in data["shots"]), 30.0, delta=1.5)

    def test_audit_flags_monotony(self):
        flat = BeatSheet(target_duration=15.0, shots=[
            Shot(index=i, duration=5.0, framing="MS", camera_move="static",
                 energy=3, subject="same", action="same")
            for i in range(1, 4)])
        problems = " ".join(audit(flat))
        self.assertIn("distinct framings", problems)
        self.assertIn("identical subject+action", problems)

    def test_audit_flags_static_runs(self):
        sheet = BeatSheet(target_duration=20.0, shots=[
            Shot(index=1, duration=4.0, framing="CU", camera_move="static", energy=2),
            Shot(index=2, duration=4.0, framing="MS", camera_move="static", energy=3),
            Shot(index=3, duration=4.0, framing="WS", camera_move="static", energy=4),
            Shot(index=4, duration=4.0, framing="MCU", camera_move="dolly-in", energy=5),
            Shot(index=5, duration=4.0, framing="ECU", camera_move="static", energy=3),
        ])
        problems = " ".join(audit(sheet))
        self.assertIn("repeated 3x in a row", problems)
        self.assertIn("static", problems)

    def test_planner_without_model_still_produces_plan(self):
        result = Planner(None).plan("a courier delivers a secret", total=30.0, shot_count=5)
        self.assertEqual(len(result.beat.shots), 5)
        self.assertGreaterEqual(len({s.framing for s in result.beat.shots}), 3)
        self.assertAlmostEqual(result.beat.total_duration, 30.0, delta=2.0)

    def test_rhythm_adoption_keeps_reference_durations(self):
        reference = beat()
        result = Planner(None).plan("new story", total=14.0, shot_count=3,
                                    reference=reference)
        self.assertTrue(result.adopted_reference)
        self.assertEqual([s.framing for s in result.beat.shots],
                         [s.framing for s in reference.shots])

    def test_enforce_variety_breaks_static_runs(self):
        sheet = BeatSheet(target_duration=20.0, shots=[
            Shot(index=1, duration=4.0, framing="CU", camera_move="static", energy=2,
                 action="他走進雨裡"),
            Shot(index=2, duration=4.0, framing="MS", camera_move="static", energy=3,
                 action="他伸出手"),
            Shot(index=3, duration=4.0, framing="WS", camera_move="static", energy=4,
                 action="他抬頭"),
            Shot(index=4, duration=4.0, framing="MCU", camera_move="static", energy=5,
                 action="他轉頭"),
            Shot(index=5, duration=4.0, framing="ECU", camera_move="static", energy=3,
                 action="雨落下"),
        ])
        fixes = enforce_variety(sheet)
        moves = [s.camera_move for s in sheet.shots]
        self.assertTrue(fixes)
        self.assertGreaterEqual(len(set(moves)), 3)
        self.assertLessEqual(moves.count("static"), 2)
        self.assertNotIn("static repeated", " ".join(audit(sheet)))

    def test_move_aliases_are_normalised(self):
        from cineagent.beatsheet import normalise_move, normalise_framing
        self.assertEqual(normalise_move("push-in"), "dolly-in")
        self.assertEqual(normalise_move("Tracking"), "truck-right")
        self.assertEqual(normalise_move("steadicam"), "handheld")
        self.assertEqual(normalise_move("nonsense"), "static")
        self.assertEqual(normalise_framing("close up"), "CU")
        self.assertEqual(normalise_framing("wide shot"), "WS")
        self.assertEqual(normalise_framing("???", ), "MS")


class RoutingTests(unittest.TestCase):
    def test_duration_snapping_respects_model_limits(self):
        kling2 = next(s for s in routing.VIDEO_MODELS if s.id == "kling/kling-v2-6")
        kling3 = next(s for s in routing.VIDEO_MODELS if s.id == "kling/kling-v3")
        veo = next(s for s in routing.VIDEO_MODELS if s.id == "google/veo-3.1")
        self.assertEqual(routing.snap_duration(kling2, 4.0), 5)
        self.assertEqual(routing.snap_duration(kling2, 8.0), 10)
        self.assertEqual(routing.snap_duration(kling3, 4.0), 4)
        self.assertEqual(routing.snap_duration(kling3, 12.4), 12)
        self.assertEqual(routing.snap_duration(veo, 5.0), 4)
        self.assertEqual(routing.snap_duration(veo, 7.6), 8)

    def test_every_capability_has_candidates(self):
        for capability in ("video", "image", "vlm", "llm"):
            self.assertTrue(routing.REGISTRY[capability])

    def test_video_models_declare_first_last_frame(self):
        for spec in routing.VIDEO_MODELS:
            self.assertTrue(spec.first_last_frame, spec.id)

    def test_health_rejects_unlisted(self):
        spec = routing.VIDEO_MODELS[0]
        ok, why = routing._health(spec, {})  # noqa: SLF001
        self.assertFalse(ok)
        self.assertIn("not listed", why)

    def test_health_accepts_matching_capability(self):
        spec = routing.IMAGE_MODELS[0]
        catalog = {spec.id: {"endpoint_capabilities": ["image_generation"]}}
        ok, _ = routing._health(spec, catalog)  # noqa: SLF001
        self.assertTrue(ok)

    def test_report_shape(self):
        router = routing.Router()
        router._catalogs = {"orcarouter": {}, "openrouter": {}}  # offline
        report = router.report()
        self.assertEqual(set(report), {"video", "image", "vlm", "llm"})
        self.assertTrue(all("model" in row for row in report["video"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
