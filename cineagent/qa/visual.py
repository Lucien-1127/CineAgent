"""Semantic / Visual QA — checks the clip against its ShotSpec + VisualBible.

Real checking needs a multimodal model; the interface + a Mock implementer let
the pipeline and tests run today. Status: interface `implemented`, real model
adapters `planned`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..domain.job import QAReport
from ..domain.shot import ShotSpec
from ..domain.visual import VisualBible


class VisualQAProvider(ABC):
    """Assess whether a generated media artifact satisfies a ShotSpec."""

    name = "visual-qabase"

    @abstractmethod
    async def assess(
        self,
        media_path: str,
        shot: ShotSpec,
        bible: Optional[VisualBible] = None,
    ) -> QAReport:
        raise NotImplementedError


class MockVisualQA(VisualQAProvider):
    """Deterministic: passes unless configured otherwise (test/offline)."""

    name = "visual-qa-mock"

    def __init__(self, problems: Optional[list] = None, threshold: float = 0.6) -> None:
        self.problems = list(problems or [])
        self.threshold = threshold

    async def assess(
        self,
        media_path: str,
        shot: ShotSpec,
        bible: Optional[VisualBible] = None,
    ) -> QAReport:
        if self.problems:
            return QAReport(
                shot_id=shot.shot_id, stage="visual", score=0.2,
                threshold=self.threshold, decision="repair",
                problems=self.problems,
                severities=["medium"] * len(self.problems),
                repair_instructions="regenerate clip with stricter prompt adherence",
            )
        return QAReport(
            shot_id=shot.shot_id, stage="visual", score=1.0,
            threshold=self.threshold, decision="pass",
            problems=[], severities=[], repair_instructions="",
        )
