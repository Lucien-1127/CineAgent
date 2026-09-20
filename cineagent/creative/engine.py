"""ScriptEngine — end-to-end creative pipeline.

Topic -> CreativeBrief -> >=3 Hooks -> pick best -> Script -> Critic (loop) -> Fact check
"""
from __future__ import annotations

from typing import Optional

from ..domain.enums import Platform, ScriptStrategy
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
        platform: Platform = Platform.SHORTS,
    ) -> ScriptPackage:
        brief = await self.planner.plan(provider, topic, hints, platform)
        best_hook = await self.hooks.generate(provider, brief, platform)
        pkg = await self.writer.write(provider, brief, best_hook.text, strategy, platform)
        pkg.metadata["hook_candidates"] = [
            candidate.model_dump() for candidate in self.hooks.last_candidates
        ]

        self.last_critiques = []
        for _round in range(MAX_CRITIC_ROUNDS):
            verdict = await self.critic.critique(provider, pkg)
            self.last_critiques.append(verdict)
            if verdict.passed:
                break
            pkg = await self.writer.write(
                provider, brief, pkg.hook, strategy, platform,
                revision_guidance=verdict.revision_guidance,
            )
            pkg.metadata["hook_candidates"] = [
                candidate.model_dump() for candidate in self.hooks.last_candidates
            ]
        else:
            # After max rounds, keep last revision; record failure but don't lose work.
            if not self.last_critiques or not self.last_critiques[-1].passed:
                pkg.metadata["critic_rounds_exhausted"] = True

        if self.critic.needs_fact_check(strategy) and pkg.facts:
            pkg = await self.fact_verifier.verify(provider, pkg)

        return pkg
