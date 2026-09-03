"""ScriptEngine — end-to-end creative pipeline.

Topic -> CreativeBrief -> >=3 Hooks -> pick best -> Script -> Critic (loop) -> Fact check
"""
from __future__ import annotations

from typing import Optional

from ..domain.enums import ScriptStrategy
from ..domain.script import CreativeBrief, ScriptPackage
from ..providers.base import ProviderError, TextProvider
from .critic import ScriptCritic
from .fact_check import FactVerifier
from .hook import HookGenerator
from .planner import CreativePlanner
from .script_writer import ScriptWriter

MAX_CRITIC_ROUNDS = 2


class ScriptEngine:
    """Orchestrates the creative phase. JSON parse failures are NOT accepted as free text."""

    def __init__(self) -> None:
        self.planner = CreativePlanner()
        self.hooks = HookGenerator()
        self.writer = ScriptWriter()
        self.critic = ScriptCritic()
        self.fact_verifier = FactVerifier()
        self.last_critiques = []

    async def run(
        self,
        provider: TextProvider,
        topic: str,
        strategy: ScriptStrategy = ScriptStrategy.SHORT_VIRAL,
        hints: Optional[str] = None,
    ) -> ScriptPackage:
        brief = await self.planner.plan(provider, topic, hints)
        best_hook = await self.hooks.generate(provider, brief)
        pkg = await self.writer.write(provider, brief, best_hook.text, strategy)

        self.last_critiques = []
        for _round in range(MAX_CRITIC_ROUNDS):
            verdict = await self.critic.critique(provider, pkg)
            self.last_critiques.append(verdict)
            if verdict.passed:
                break
            pkg = await self.writer.write(
                provider, brief, pkg.hook, strategy,
            )
        else:
            # After max rounds, keep last revision; record failure but don't lose work.
            if not self.last_critiques or not self.last_critiques[-1].passed:
                pkg.metadata["critic_rounds_exhausted"] = True

        if self.critic.needs_fact_check(strategy) and pkg.facts:
            pkg = await self.fact_verifier.verify(provider, pkg)

        return pkg
