"""StoryboardDirector — produce canonical ShotSpecs (never vendor prompts).

This module does NOT compile vendor prompts. It only renders the story into
provider-independent ShotSpec objects; PromptCompiler (and vendor-specific
compilers) handle prompt emission later.
"""
from __future__ import annotations

import re
from typing import List, Optional

from ..domain.enums import CameraMotion, GenerationStrategy, QualityTier, ShotSize
from ..domain.script import ScriptPackage
from ..domain.shot import ShotSpec
from ..domain.visual import VisualBible

_SENTENCE_RE = re.compile(r"[。！？!?]+")


class StoryboardDirector:
    """Phase: Final Script + VisualBible -> List[ShotSpec] (canonical)."""

    def direct(
        self,
        script: ScriptPackage,
        bible: Optional[VisualBible] = None,
        scene_timing: Optional[dict] = None,
    ) -> List[ShotSpec]:
        """One Shot per narration sentence (a shot-sized unit).

        `scene_timing`: {scene_id: (start, end)} in seconds from the Audio
        timeline phase; when absent, shots get placeholder (0,0) timing that the
        audio phase will fill.
        """
        shots: List[ShotSpec] = []
        idx = 0
        for scene in script.scenes:
            sentences = self._split_sentences(scene.narration) or [scene.narration]
            start, end = self._scene_timing(scene_timing, scene.scene_id)
            seg_len = (end - start) / max(1, len(sentences)) if end > start else 0.0
            for i, sentence in enumerate(sentences):
                shot_start = start + i * seg_len if end > start else 0.0
                shot_end = shot_start + seg_len if end > start else 0.0
                shots.append(ShotSpec(
                    shot_id=f"shot-{idx}",
                    scene_id=scene.scene_id,
                    start_time=round(shot_start, 3),
                    end_time=round(shot_end, 3),
                    duration=round(shot_end - shot_start, 3),
                    narration_segment=sentence,
                    visual_goal=scene.goal,
                    subject=scene.title,
                    action="",
                    location="",
                    shot_size=ShotSize.MEDIUM,
                    camera_motion=CameraMotion.STATIC,
                    generation_strategy=GenerationStrategy.GENERATED_IMAGE,
                    quality_tier=QualityTier.BALANCED,
                    reference_images=list(bible.reference_assets) if bible else [],
                    provider_constraints=list(bible.negative_constraints) if bible else [],
                ))
                idx += 1
        return shots

    def _split_sentences(self, text: str) -> List[str]:
        parts = [p.strip() for p in _SENTENCE_RE.split(text) if p.strip()]
        return parts

    def _scene_timing(self, timing: Optional[dict], scene_id: str):
        if timing and scene_id in timing:
            return timing[scene_id]
        return (0.0, 0.0)
