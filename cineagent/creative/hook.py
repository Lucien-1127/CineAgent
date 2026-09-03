"""HookGenerator — generate >=N hook candidates, score, pick the best."""
from __future__ import annotations

from typing import List

from ..domain.script import CreativeBrief, HookCandidate, HookSet
from ..providers.base import TextProvider


class HookGenerator:
    """Phase: -> >=3 Hook candidates -> scored -> best hook."""

    MIN_CANDIDATES = 3

    async def generate(self, provider: TextProvider, brief: CreativeBrief) -> HookCandidate:
        system = (
            "你是短影音開場專家。產出至少 3 個 Hook 候選，跨不同的 hook 類型 "
            "(question / shocking / story / stat / cta)。每個候選附 0~1 的吸引力分數與理由。"
        )
        user = f"主題訊息：{brief.core_message or brief.content_type}\n受眾：{brief.audience}"
        hooks = await provider.structured(HookSet, system, user, temperature=0.8)
        candidates = self._ensure_min(hooks.candidates)
        scored = sorted(candidates, key=self._rank, reverse=True)
        best = scored[0]
        return best

    def _ensure_min(self, candidates: List[HookCandidate]) -> List[HookCandidate]:
        if len(candidates) < self.MIN_CANDIDATES:
            raise ValueError(
                f"hook generator returned {len(candidates)} candidates; "
                f"need >= {self.MIN_CANDIDATES}"
            )
        return candidates

    def _rank(self, c: HookCandidate) -> float:
        """Deterministic tiebreak: prefer non-empty text; then provider score."""
        text_score = 0.0 if not c.text.strip() else 0.1
        return c.score + text_score
