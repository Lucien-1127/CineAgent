"""ScriptCritic — review a script package and return a structured verdict."""
from __future__ import annotations

from ..domain.enums import ScriptStrategy
from ..domain.script import CritiqueResult, ScriptPackage
from ..providers.base import TextProvider

CRITIC_REQUIRE_MESSAGES = {
    ScriptStrategy.EDUCATIONAL, ScriptStrategy.EXPLAINER,
    ScriptStrategy.DOCUMENTARY, ScriptStrategy.PRODUCT_AD,
}


class ScriptCritic:
    """Phase: Script -> review -> pass/fail + revision guidance."""

    async def critique(
        self, provider: TextProvider, pkg: ScriptPackage,
    ) -> CritiqueResult:
        strategy = pkg.script_strategy
        system = (
            "你是嚴格的短影音 retention 編輯。分別評估 Hook、前 3 秒承諾、持續留存設計、"
            "payoff、原創性與平台原生感。檢查是否有空泛前言、重複資訊、與內容無關的"
            "clickbait、過早 CTA 或缺乏視覺/語意變化。只在核心維度足夠時 passed=true，"
            "否則提供可直接交給 Writer 的 revision_guidance 與 retention_risks。"
        )
        user = (
            f"平台：{pkg.platform.value}\n結構：{strategy.value}\nHook：{pkg.hook}\n"
            f"旁白：{pkg.narration}\nCTA：{pkg.cta}\n場景："
            + "\n".join(
                f"{scene.index}. {scene.title}｜{scene.goal}｜{scene.narration}"
                for scene in pkg.scenes
            )
        )
        return await provider.structured(CritiqueResult, system, user, temperature=0.2)

    def needs_fact_check(self, strategy: ScriptStrategy) -> bool:
        return strategy in CRITIC_REQUIRE_MESSAGES
