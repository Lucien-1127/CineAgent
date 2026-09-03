"""CreativePlanner — turn a topic into a validated CreativeBrief."""
from __future__ import annotations

from typing import Optional

from ..domain.script import CreativeBrief
from ..providers.base import TextProvider


class CreativePlanner:
    """Phase: Topic -> CreativeBrief."""

    async def plan(
        self,
        provider: TextProvider,
        topic: str,
        hints: Optional[str] = None,
    ) -> CreativeBrief:
        system = (
            "你是 CineAgent 的創意總監。根據主題產出一份結構化的單集創意簡報 "
            "(CreativeBrief)。所有欄位用精簡、具體的中文填寫。"
        )
        user = f"主題：{topic}\n補充（可留空）：{hints or ''}"
        brief = await provider.structured(CreativeBrief, system, user, temperature=0.5)
        if not brief:
            raise ValueError("planner returned empty brief")
        return brief
