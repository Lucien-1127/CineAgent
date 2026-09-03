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
            "你是嚴格的腳本審查員。檢查：Hook 是否強而有力、旁白是否通順、"
            "場景是否連貫、是否偏離指定結構、CTA（若適用）是否明確。"
        )
        user = (
            f"結構：{strategy.value}\nHook：{pkg.hook}\n旁白：{pkg.narration}\n"
            f"場景數：{len(pkg.scenes)}"
        )
        return await provider.structured(CritiqueResult, system, user, temperature=0.2)

    def needs_fact_check(self, strategy: ScriptStrategy) -> bool:
        return strategy in CRITIC_REQUIRE_MESSAGES
