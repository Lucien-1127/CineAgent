"""HookGenerator — generate >=N hook candidates, score, pick the best."""
from __future__ import annotations

from typing import List

from ..domain.enums import Platform
from ..domain.script import CreativeBrief, HookCandidate, HookSet
from ..providers.base import TextProvider


class HookGenerator:
    """Phase: -> >=3 Hook candidates -> scored -> best hook."""

    MIN_CANDIDATES = 3

    def __init__(self) -> None:
        self.last_candidates: List[HookCandidate] = []

    async def generate(
        self,
        provider: TextProvider,
        brief: CreativeBrief,
        platform: Platform = Platform.SHORTS,
    ) -> HookCandidate:
        system = (
            "你是短影音開場專家。產出至少 3 個真正不同的 Hook 候選，跨 question / "
            "surprise / story / stat / demonstration 類型。前 2 秒要讓目標受眾停止滑動，"
            "前 3 秒清楚兌現主題承諾；不得使用與內容無關的 clickbait。每個候選分別評估"
            " audience_relevance、promise_clarity、curiosity、payoff_alignment、credibility。"
        )
        user = (
            f"平台：{platform.value}\n主題訊息：{brief.core_message or brief.content_type}\n"
            f"受眾：{brief.audience}\n受眾痛點：{brief.audience_problem}\n"
            f"觀看承諾：{brief.viewer_promise}\n原創角度：{brief.novelty_angle}"
        )
        hooks = await provider.structured(HookSet, system, user, temperature=0.8)
        candidates = self._ensure_min(hooks.candidates)
        scored = sorted(candidates, key=self._rank, reverse=True)
        self.last_candidates = scored
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
        """Rank the hook on audience value, not provider self-score alone."""
        if not c.text.strip():
            return 0.0
        return (
            c.score * 0.20
            + c.audience_relevance * 0.20
            + c.promise_clarity * 0.20
            + c.curiosity * 0.15
            + c.payoff_alignment * 0.15
            + c.credibility * 0.10
        )
