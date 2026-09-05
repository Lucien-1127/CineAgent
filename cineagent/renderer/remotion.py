"""Remotion renderer — primary, scripted (status: planned).

Requires a Node + Remotion project. Pipelines fall back to FFmpegRenderer until
a Remotion project + Node runtime are wired (documented in Phase 8 / DoD 10).
"""
from __future__ import annotations

from .base import RenderComposition, RendererProvider


class RemotionRenderer(RendererProvider):
    name = "remotion"
    status = "planned"

    async def render(self, comp: RenderComposition) -> str:
        raise NotImplementedError(
            "RemotionRenderer is 'planned'. Provide renderer/Remotion project + "
            "Node runtime, then implement render(); fall back to FFmpegRenderer."
        )
