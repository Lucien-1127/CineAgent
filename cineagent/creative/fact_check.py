"""FactVerifier — verify claims for informational content.

Status: `experimental`. Real verification requires external source grounding;
the provider-pass through validates structure and flags unverified facts.
"""
from __future__ import annotations

from ..domain.script import Fact, ScriptPackage
from ..providers.base import TextProvider


class FactVerifier:
    """Phase: Fact check (only for informational strategies)."""

    async def verify(self, provider: TextProvider, pkg: ScriptPackage) -> ScriptPackage:
        if not pkg.facts:
            return pkg
        system = (
            "你是事實查核員。逐條評估下列事實聲明，標註 verified 與 confidence。"
            "無法以可靠來源佐證者，verified 必須為 False。"
        )
        user = "\n".join(f"- {f.statement}" for f in pkg.facts)
        verified_facts: list[Fact] = []
        # structured-pass: ask provider for a validated facts list
        from typing import List
        from pydantic import BaseModel, Field as _F

        class _FactList(BaseModel):
            facts: List[Fact] = _F(default_factory=list)

        result = await provider.structured(_FactList, system, user, temperature=0.1)
        # Merge by statement text.
        by_stmt = {f.statement: f for f in result.facts}
        for f in pkg.facts:
            merged = by_stmt.get(f.statement, f)
            verified_facts.append(merged)
        pkg.facts = verified_facts
        return pkg
