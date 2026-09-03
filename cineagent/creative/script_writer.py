"""ScriptWriter — produce a validated ScriptPackage from brief + chosen hook."""
from __future__ import annotations

from ..domain.enums import ScriptStrategy
from ..domain.script import CreativeBrief, ScriptPackage
from ..providers.base import TextProvider


class ScriptWriter:
    """Phase: Brief+Hook -> Script (structured, strategy-aware)."""

    STRATEGY_PATTERNS = {
        ScriptStrategy.SHORT_VIRAL: "Hook -> Retention -> Mechanism/Value -> Payoff -> optional CTA",
        ScriptStrategy.EDUCATIONAL: "Hook -> Core question -> Explain -> Example -> Takeaway",
        ScriptStrategy.STORYTELLING: "Setup -> Conflict -> Climax -> Resolution",
        ScriptStrategy.PRODUCT_AD: "Hook -> Problem -> Solution -> Proof -> CTA",
        ScriptStrategy.EXPLAINER: "Hook -> Context -> How-it-works -> Recap",
        ScriptStrategy.DOCUMENTARY: "Cold open -> Context -> Depth -> Resolution",
        ScriptStrategy.CINEMATIC: "Establishing -> Rising tension -> Peak -> Denouement",
    }

    async def write(
        self,
        provider: TextProvider,
        brief: CreativeBrief,
        hook: str,
        strategy: ScriptStrategy = ScriptStrategy.SHORT_VIRAL,
    ) -> ScriptPackage:
        pattern = self.STRATEGY_PATTERNS.get(strategy, self.STRATEGY_PATTERNS[ScriptStrategy.SHORT_VIRAL])
        system = (
            f"你是資深編劇。依「{pattern}」結構撰寫旁白（narration）與場景（scenes）。"
            "禁止對所有影片套同一種故事理論——請依指定的 script_strategy 調整結構。"
        )
        user = (
            f"Hook：{hook}\n核心訊息：{brief.core_message}\n"
            f"受眾：{brief.audience}\n情感目標：{brief.emotional_goal}\n"
            f"禁止元素：{'、'.join(brief.prohibited_elements) or '無'}"
        )
        pkg = await provider.structured(ScriptPackage, system, user, temperature=0.7)
        pkg.hook = hook  # enforce the chosen hook
        pkg.script_strategy = strategy
        return pkg
