"""Seedance adapter — Volcano Engine Ark content-generation API.

Verified against official docs (docs.volcengine.com/docs/82379/1520757 create,
1521309 query, 2298881 tutorial). See references/video-provider-verification.md
for the exact field/source mapping and the UNVERIFIED list.

Auth: ``ARK_API_KEY`` env var (Bearer). The adapter drops unsupported params
rather than forwarding them (see ``MODEL_CAPS``).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..base import classify_http_status
from .generation import download_video
from .schemas import (
    VideoGenerationRequest,
    VideoTask,
    VideoTaskState,
    VideoTaskStatus,
)

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

# Capabilities verified from the official tutorial (2298881) + create/query docs.
# Keys are feature names; a model "supports" a feature only if listed here.
# duration bounds are (min, max) integer seconds.
MODEL_CAPS: Dict[str, Dict[str, Any]] = {
    "doubao-seedance-2-5-260628": {
        "duration": (4, 30), "native_audio": True, "last_frame": True,
        "reference_image": True, "reference_video": True, "reference_audio": True,
    },
    "doubao-seedance-2-0-260128": {
        "duration": (4, 15), "native_audio": True, "last_frame": True,
        "reference_image": True, "reference_video": True, "reference_audio": True,
    },
    "doubao-seedance-2-0-fast-260128": {
        "duration": (4, 15), "native_audio": True, "last_frame": True,
        "reference_image": True, "reference_video": True, "reference_audio": True,
    },
    "doubao-seedance-2-0-mini-260615": {
        "duration": (4, 15), "native_audio": True, "last_frame": True,
        "reference_image": True, "reference_video": True, "reference_audio": True,
    },
    "doubao-seedance-1-5-pro-251215": {
        "duration": (4, 12), "native_audio": True, "last_frame": True,
        "reference_image": False, "reference_video": False, "reference_audio": False,
    },
    "doubao-seedance-1-0-pro-250528": {
        "duration": (2, 12), "native_audio": False, "last_frame": True,
        "reference_image": False, "reference_video": False, "reference_audio": False,
    },
    "doubao-seedance-1-0-pro-fast-251015": {
        "duration": (2, 12), "native_audio": False, "last_frame": False,
        "reference_image": False, "reference_video": False, "reference_audio": False,
    },
}

_STATUS_MAP = {
    "queued": VideoTaskState.QUEUED,
    "running": VideoTaskState.RUNNING,
    "succeeded": VideoTaskState.SUCCEEDED,
    "failed": VideoTaskState.FAILED,
    "expired": VideoTaskState.EXPIRED,
}


class SeedanceVideoProvider:
    """Volcano Engine Ark Seedance video generation."""

    name = "seedance"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("ARK_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # ── public contract ────────────────────────────────────────────────
    async def create_task(self, request: VideoGenerationRequest) -> VideoTask:
        payload = self.build_payload(request)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/contents/generations/tasks",
                headers=self._headers(),
                json=payload,
            )
        self._raise_for(resp)
        data = resp.json()
        return VideoTask(
            provider=self.name,
            model=request.model,
            remote_job_id=data.get("id", ""),
            status=VideoTaskState.QUEUED,
        )

    async def get_task(self, remote_job_id: str) -> VideoTaskStatus:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/contents/generations/tasks/{remote_job_id}",
                headers=self._headers(),
            )
        self._raise_for(resp)
        return self.parse_status(resp.json())

    async def download_result(self, task: VideoTaskStatus, output_path: Path) -> Path:
        if not task.video_url:
            raise IOError("no video_url present; cannot download")
        return await download_video(task.video_url, output_path, timeout=self.timeout)

    # ── payload / response mapping (public for tests) ──────────────────
    def build_payload(self, request: VideoGenerationRequest) -> Dict[str, Any]:
        """Assemble the Ark request body, dropping unsupported fields.

        Unsupported features are silently filtered (never forwarded). The
        returned dict is exactly what is POSTed.
        """
        caps = MODEL_CAPS.get(request.model)
        if caps is None:
            raise ValueError(f"unknown Seedance model: {request.model!r}")

        content: List[Dict[str, Any]] = []
        if request.prompt:
            content.append({"type": "text", "text": request.prompt})

        first = request.first_frame
        if first:
            if request.end_frame_url and caps["last_frame"]:
                content.append({"type": "image_url", "image_url": {"url": first},
                                "role": "first_frame"})
                content.append({"type": "image_url", "image_url": {"url": request.end_frame_url},
                                "role": "last_frame"})
            else:
                # last_frame unsupported (or absent) => degrade to first-frame only.
                content.append({"type": "image_url", "image_url": {"url": first},
                                "role": "first_frame"})

        if caps["reference_image"]:
            for img in request.reference_images:
                content.append({"type": "image_url", "image_url": {"url": img},
                                "role": "reference_image"})
        if caps["reference_video"]:
            for vid in request.reference_videos:
                content.append({"type": "video_url", "video_url": {"url": vid},
                                "role": "reference_video"})
        if request.audio_url and caps["reference_audio"]:
            content.append({"type": "audio_url", "audio_url": {"url": request.audio_url},
                            "role": "reference_audio"})

        payload: Dict[str, Any] = {"model": request.model, "content": content}
        if request.aspect_ratio:
            payload["ratio"] = request.aspect_ratio
        if request.resolution:
            payload["resolution"] = request.resolution
        payload["duration"] = _clamp_duration(request.duration_seconds, caps["duration"])
        if request.seed is not None:
            payload["seed"] = request.seed
        if request.native_audio and caps["native_audio"]:
            payload["generate_audio"] = True
        # Ask for the tail frame so stitching can link segments without re-probing.
        # Only for models that support last-frame output; otherwise the stitching
        # layer extracts it locally via ffmpeg.
        if caps["last_frame"]:
            payload["return_last_frame"] = True
        return payload

    def parse_status(self, data: Dict[str, Any]) -> VideoTaskStatus:
        state = _STATUS_MAP.get(data.get("status", "unknown"), VideoTaskState.UNKNOWN)
        content = data.get("content") or {}
        error = data.get("error") or {}
        return VideoTaskStatus(
            remote_job_id=data.get("id", ""),
            state=state,
            video_url=content.get("video_url"),
            last_frame_url=content.get("last_frame_url"),
            duration_seconds=_as_float(data.get("duration")),
            error_code=error.get("code"),
            error_message=error.get("message"),
            raw=data,
        )

    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            raise classify_http_status(resp.status_code, resp.text)


def _clamp_duration(duration: int, bounds: tuple[int, int]) -> int:
    lo, hi = bounds
    return max(lo, min(hi, duration))


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = ["SeedanceVideoProvider", "MODEL_CAPS", "DEFAULT_BASE_URL"]
