"""ScriptWriter — produce a validated ScriptPackage from brief + chosen hook."""
from __future__ import annotations

from ..domain.enums import Platform, ScriptStrategy
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
        platform: Platform = Platform.SHORTS,
        revision_guidance: str = "",
    ) -> ScriptPackage:
        pattern = self.STRATEGY_PATTERNS.get(strategy, self.STRATEGY_PATTERNS[ScriptStrategy.SHORT_VIRAL])
        system = (
            f"你是資深編劇。依「{pattern}」結構撰寫旁白（narration）與場景（scenes）。"
            "禁止對所有影片套同一種故事理論——請依指定的 script_strategy 調整結構。"
            "短影音必須在前 3 秒兌現 Hook 承諾，每個段落只增加一個新資訊，安排視覺或語意"
            "pattern interrupt，並在結尾交付明確 payoff；CTA 必須自然且不得早於價值交付。"
        )
        user = (
            f"平台：{platform.value}\nHook：{hook}\n核心訊息：{brief.core_message}\n"
            f"受眾：{brief.audience}\n情感目標：{brief.emotional_goal}\n"
            f"觀看承諾：{brief.viewer_promise}\n原創角度：{brief.novelty_angle}\n"
            f"證據：{'、'.join(brief.proof_points) or '無'}\n"
            f"禁止元素：{'、'.join(brief.prohibited_elements) or '無'}\n"
            f"上一輪修訂要求：{revision_guidance or '無'}"
        )
        pkg = await provider.structured(ScriptPackage, system, user, temperature=0.7)
        pkg.hook = hook  # enforce the chosen hook
        pkg.script_strategy = strategy
        pkg.platform = platform
        return pkg
