"""Regression tests: no provider requests, no real rendering."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cineagent import gate, pipeline
from run_pipeline import main


class VerifiedDeliveryTests(unittest.TestCase):
    def test_low_motion_cannot_hide_behind_identity(self):
        report = gate.GateReport(identity=100, wardrobe=100, palette=100,
                                 framing=100, motion=30, verdict="accept")
        self.assertEqual(gate.decide(report).verdict, "retry")

    def test_low_framing_cannot_hide_behind_identity(self):
        report = gate.GateReport(identity=100, wardrobe=100, palette=100,
                                 framing=30, motion=100, verdict="accept")
        self.assertEqual(gate.decide(report).verdict, "retry")

    def test_missing_and_malformed_scores(self):
        for value in ('null', 'true', '"90"', 'NaN', '101', '-1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gate.parse_report('{"identity":90,"wardrobe":90,"palette":90,'
                                  '"framing":90,"motion":' + value + ',"verdict":"accept"}')
        with self.assertRaises(ValueError):
            gate.parse_report('{"identity":90,"verdict":"accept"}')

    def test_gate_unavailable_escalates(self):
        pipe = pipeline.Pipeline()
        with patch.object(pipeline.media, "probe", side_effect=RuntimeError("offline")):
            decision, report = pipe.gate_shot(Path("v.mp4"), Path("ref.png"), 5, "move", Path("."))
        self.assertEqual(decision.verdict, "escalate")
        self.assertIsNone(report)

    def test_dry_render_never_resolves_provider(self):
        pipe = pipeline.Pipeline(pipeline.Config(dry_run=True))
        from cineagent.beatsheet import Shot, BeatSheet
        from cineagent.anchor import AnchorSheet, CharacterAnchor
        sheet = AnchorSheet()
        sheet.add(CharacterAnchor(anchor_id="lead", name="Lead", canonical="person"))
        with tempfile.TemporaryDirectory() as tmp, patch.object(
                pipe, "video_client", side_effect=AssertionError("unexpected network")):
            path = pipe.render_shot(Shot(index=1, duration=5), None, BeatSheet(), sheet, Path(tmp))
            self.assertEqual(path.read_bytes(), b"DRY-RUN")

    def test_cli_rejected_mp4_is_nonzero(self):
        with patch.object(pipeline.Pipeline, "run", return_value={"final":"candidate.mp4","accepted":False}), patch.object(pipeline.Pipeline, "summary_text", return_value="test"):
            self.assertEqual(main(["run","--brief","test"]), 1)

    def test_dry_run_is_never_delivery(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
                pipeline.Router, "resolve", side_effect=AssertionError("unexpected network")):
            pipe = pipeline.Pipeline(pipeline.Config(outdir=Path(tmp), dry_run=True))
            report = pipe.run("a worker records one purchase", duration=30, shots=5)
            self.assertFalse(report["accepted"])
            self.assertEqual(report["delivery_status"], "NOT_RUN")
            self.assertEqual(report["performance_review"]["status"], "NOT_RUN")
            self.assertEqual(report["final"], "")
