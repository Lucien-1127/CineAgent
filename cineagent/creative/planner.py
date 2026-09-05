"""CreativePlanner — turn a topic into a validated CreativeBrief."""
from __future__ import annotations

from typing import Optional

from ..domain.enums import Platform
from ..domain.script import CreativeBrief
from ..providers.base import TextProvider


class CreativePlanner:
    """Phase: Topic -> CreativeBrief."""

    async def plan(
        self,
        provider: TextProvider,
        topic: str,
        hints: Optional[str] = None,
        platform: Platform = Platform.SHORTS,
    ) -> CreativeBrief:
        system = (
            "你是 CineAgent 的創意總監。根據主題產出一份結構化的單集創意簡報 "
            "(CreativeBrief)。先定義受眾痛點、可立即理解的觀看承諾、原創觀點、"
            "可驗證證據與平台原生風格。趨勢只能使用補充資料中已提供的資訊，禁止捏造。"
            "所有欄位用精簡、具體的中文填寫。"
        )
        user = f"平台：{platform.value}\n主題：{topic}\n補充（可留空）：{hints or ''}"
        brief = await provider.structured(CreativeBrief, system, user, temperature=0.5)
        if not brief:
            raise ValueError("planner returned empty brief")
        return brief
