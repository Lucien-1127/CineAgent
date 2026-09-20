"""Async generation contract shared by real video providers.

Seedance and Kling both expose an async submit -> poll -> download lifecycle.
This module defines that contract (a Protocol) plus a streaming download
helper so the planner and stitching code stay provider-neutral.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx

from .schemas import VideoGenerationRequest, VideoTask, VideoTaskStatus


@runtime_checkable
class GenerationProvider(Protocol):
    """Provider-neutral async video generation contract.

    Implementations: SeedanceVideoProvider, KlingVideoProvider,
    and the offline mock used in tests.
    """

    name: str

    async def create_task(self, request: VideoGenerationRequest) -> VideoTask:
        """Submit a generation task and return a durable remote handle."""

    async def get_task(self, remote_job_id: str) -> VideoTaskStatus:
        """Query task state without re-submitting (resume-safe)."""

    async def download_result(self, task: VideoTaskStatus, output_path: Path) -> Path:
        """Download a succeeded task's video to disk and return the path."""


async def download_video(
    url: str,
    output_path: Path,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 120.0,
) -> Path:
    """Stream a result URL to disk. Raises on non-200 or network failure."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    try:
        async with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                raise IOError(
                    f"download failed: HTTP {resp.status_code} for {url}"
                )
            with open(output_path, "wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)
    finally:
        if owns:
            await client.aclose()
    return output_path


__all__ = ["GenerationProvider", "download_video"]
