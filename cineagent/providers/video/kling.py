"""Kling adapter — Kuaishou Kling legacy ``/v1/videos/*`` API (JWT auth).

The legacy API is the most consistently documented contract (official upstream
mirrored by multiple providers). The newer "API 2.0" (2026-06) is a JS-app
portal and is NOT implemented here; see references/video-provider-verification.md.

Auth: ``KLING_ACCESS_KEY`` + ``KLING_SECRET_KEY`` env vars (self-signed JWT).
Unsupported params are dropped rather than forwarded.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
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

DEFAULT_BASE_URL = "https://api-singapore.klingai.com"

# Legacy model_name values (documented upstream; kling-v2-1/-master are I2V-only).
TEXT_TO_VIDEO_MODELS = {
    "kling-v1", "kling-v1-5", "kling-v1-6", "kling-v2", "kling-v2-master",
    "kling-v2-5", "kling-v2-5-turbo", "kling-v2-6", "kling-v3",
}
IMAGE_TO_VIDEO_MODELS = TEXT_TO_VIDEO_MODELS | {"kling-v2-1", "kling-v2-1-master"}

# Native audio (`sound: "on"`) is only cross-confirmed for these two models.
NATIVE_AUDIO_MODELS = {"kling-v2-6", "kling-v3"}

_STATUS_MAP = {
    "submitted": VideoTaskState.QUEUED,
    "processing": VideoTaskState.RUNNING,
    "succeed": VideoTaskState.SUCCEEDED,
    "failed": VideoTaskState.FAILED,
}


class KlingVideoProvider:
    """Kling legacy video generation (image2video / text2video)."""

    name = "kling"

    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
    ) -> None:
        self.access_key = access_key or os.environ.get("KLING_ACCESS_KEY", "")
        self.secret_key = secret_key or os.environ.get("KLING_SECRET_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ── auth ───────────────────────────────────────────────────────────
    def _jwt(self) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        now = int(time.time())
        payload = {"iss": self.access_key, "exp": now + 1800, "nbf": now - 5}
        seg = (
            _b64url(json.dumps(header, separators=(",", ":")).encode()),
            _b64url(json.dumps(payload, separators=(",", ":")).encode()),
        )
        signing_input = f"{seg[0]}.{seg[1]}"
        sig = hmac.new(self.secret_key.encode(), signing_input.encode(), hashlib.sha256).digest()
        return f"{signing_input}.{_b64url(sig)}"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._jwt()}", "Content-Type": "application/json"}

    # ── public contract ────────────────────────────────────────────────
    async def create_task(self, request: VideoGenerationRequest) -> VideoTask:
        endpoint, payload = self.build_payload(request)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v1/videos/{endpoint}",
                headers=self._headers(),
                json=payload,
            )
        self._raise_for(resp)
        data = resp.json()
        inner = data.get("data") or {}
        return VideoTask(
            provider=self.name,
            model=request.model,
            remote_job_id=inner.get("task_id", ""),
            status=VideoTaskState.QUEUED,
        )

    async def get_task(self, remote_job_id: str) -> VideoTaskStatus:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/v1/videos/{remote_job_id}",
                headers=self._headers(),
            )
        self._raise_for(resp)
        return self.parse_status(resp.json())

    async def download_result(self, task: VideoTaskStatus, output_path: Path) -> Path:
        if not task.video_url:
            raise IOError("no video_url present; cannot download")
        return await download_video(task.video_url, output_path, timeout=self.timeout)

    # ── payload / response mapping (public for tests) ──────────────────
    def build_payload(self, request: VideoGenerationRequest) -> tuple[str, Dict[str, Any]]:
        """Return (endpoint, body). Drops unsupported fields instead of forwarding."""
        if request.model not in IMAGE_TO_VIDEO_MODELS:
            raise ValueError(f"unknown Kling model: {request.model!r}")

        body: Dict[str, Any] = {"model_name": request.model}
        if request.prompt:
            body["prompt"] = request.prompt
        if request.negative_prompt:
            body["negative_prompt"] = request.negative_prompt

        first = request.first_frame
        if first:
            endpoint = "image2video"
            body["image"] = first
            if request.end_frame_url:
                body["image_tail"] = request.end_frame_url
        else:
            endpoint = "text2video"
            if request.model not in TEXT_TO_VIDEO_MODELS:
                # I2V-only model given a text-only request => no viable task.
                raise ValueError(f"model {request.model!r} does not support text-to-video")

        if request.duration_seconds:
            body["duration"] = str(_clamp_duration(request.duration_seconds))
        if request.resolution:
            body["mode"] = _resolution_to_mode(request.resolution)
        if request.aspect_ratio and endpoint == "text2video":
            # image2video output follows the input image; ratio is only
            # reliably applied on text2video (see verification report).
            body["aspect_ratio"] = request.aspect_ratio
        if request.native_audio and request.model in NATIVE_AUDIO_MODELS:
            body["sound"] = "on"
        # NOTE: Kling legacy has no verified `seed` field and no `multi_shot`;
        # both are dropped (never fabricated into a different field).
        return endpoint, body

    def parse_status(self, data: Dict[str, Any]) -> VideoTaskStatus:
        inner = data.get("data") or {}
        raw_state = inner.get("task_status", "unknown")
        state = _STATUS_MAP.get(raw_state, VideoTaskState.UNKNOWN)
        result = inner.get("task_result") or {}
        videos = result.get("videos") or []
        video = videos[0] if videos else {}
        return VideoTaskStatus(
            remote_job_id=inner.get("task_id", ""),
            state=state,
            video_url=video.get("url"),
            duration_seconds=_as_float(video.get("duration")),
            error_message=inner.get("task_status_msg") or "",
            raw=data,
        )

    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            raise classify_http_status(resp.status_code, resp.text)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _clamp_duration(duration: int) -> int:
    # Legacy API accepts "5"/"10"; keep within the safe range and snap to enum.
    if duration <= 5:
        return 5
    return 10


def _resolution_to_mode(resolution: str) -> str:
    if resolution in ("1080p", "4k"):
        return "pro"
    return "std"


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "KlingVideoProvider",
    "DEFAULT_BASE_URL",
    "TEXT_TO_VIDEO_MODELS",
    "IMAGE_TO_VIDEO_MODELS",
    "NATIVE_AUDIO_MODELS",
]
