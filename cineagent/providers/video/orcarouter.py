"""OrcaRouter video adapter (experimental; contract tests, no live acceptance).

Source: docs.orcarouter.ai/{kling-video,seedance-video}/overview, 2026-09-18.
No documented submission idempotency contract: never claim exactly-once billing.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from ..base import AuthError, ProviderFailure, ValidationError, classify_http_status
from .generation import download_video
from .schemas import VideoTask, VideoTaskState, VideoTaskStatus

SEEDANCE = "byteplus/dreamina-seedance-2-0-260128"
KLING_MODELS = frozenset("kling/" + m for m in (
    "kling-v2-master", "kling-v2-1-master", "kling-v2-5-turbo", "kling-v2-6",
    "kling-v3", "kling-video-o1", "kling-v3-omni"))
OMNI = {"kling/kling-video-o1", "kling/kling-v3-omni"}
V3 = {"kling/kling-v3", "kling/kling-v3-omni"}


def duration_policy(model):
    if model == SEEDANCE:
        return 4, 15, None
    if model in V3:
        return 3, 15, None
    if model in KLING_MODELS:
        return 5, 10, [5, 10]
    raise ValidationError(f"unsupported OrcaRouter video model: {model}")


def _url(value):
    parts = urlsplit(value)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ValidationError("media must be an HTTP(S) URL; upload local files first")
    return value


class OrcaRouterVideoProvider:
    name = "orcarouter"
    requires_public_media = True

    def __init__(self, api_key=None, timeout=120.0, transport=None):
        self.api_key = api_key or os.environ.get("ORCAROUTER_API_KEY", "")
        self.base_url = "https://api.orcarouter.ai/v1"
        self.timeout = timeout
        self.transport = transport

    def validate_request(self, request):
        self.build_payload(request)

    def build_payload(self, request):
        minimum, maximum, allowed = duration_policy(request.model)
        if not minimum <= request.duration_seconds <= maximum or (
                allowed and request.duration_seconds not in allowed):
            raise ValidationError("duration unsupported by selected model")
        if request.multi_shot:
            raise ValidationError("multi-shot payload authoring is not implemented")
        if request.end_frame_url and not request.first_frame:
            raise ValidationError("end frame requires first frame")
        for value in [request.first_frame, request.end_frame_url, request.audio_url,
                      *request.reference_images, *request.reference_videos]:
            if value:
                _url(value)
        body = {"model": request.model, "prompt": request.prompt}
        if request.model == SEEDANCE:
            if request.negative_prompt:
                raise ValidationError("Seedance negative_prompt is not mapped; use the prompt")
            if request.resolution not in ("480p", "720p", "1080p"):
                raise ValidationError("unsupported Seedance resolution")
            if request.aspect_ratio not in ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"):
                raise ValidationError("unsupported Seedance ratio")
            content = []
            def item(kind, value, role):
                content.append({"type": kind, kind: {"url": value}, "role": role})
            if request.first_frame:
                item("image_url", request.first_frame, "first_frame")
            if request.end_frame_url:
                item("image_url", request.end_frame_url, "end_frame")
            for value in request.reference_images:
                item("image_url", value, "reference_image")
            for value in request.reference_videos:
                item("video_url", value, "reference_video")
            if request.audio_url:
                item("audio_url", request.audio_url, "reference_audio")
            meta = {"ratio": request.aspect_ratio, "resolution": request.resolution,
                    "duration": request.duration_seconds, "generate_audio": request.native_audio}
            if content:
                meta["content"] = content
            if request.seed is not None:
                meta["seed"] = request.seed
        else:
            if request.aspect_ratio not in ("16:9", "9:16", "1:1"):
                raise ValidationError("unsupported Kling aspect ratio")
            mode = {"720p": "std", "1080p": "pro", "4k": "4k"}.get(request.resolution)
            if not mode or (mode == "4k" and request.model not in V3):
                raise ValidationError("unsupported Kling resolution for selected model")
            if request.audio_url or request.seed is not None:
                raise ValidationError("Kling audio reference/seed not mapped")
            if request.native_audio and not (request.model in V3 or
                    (request.model == "kling/kling-v2-6" and mode == "pro")):
                raise ValidationError("native audio unsupported for selected model/mode")
            meta = {"duration": str(request.duration_seconds), "mode": mode,
                    "aspect_ratio": request.aspect_ratio, "sound": "on" if request.native_audio else "off"}
            if request.model in OMNI:
                if request.negative_prompt:
                    raise ValidationError("negative_prompt not supported on Omni")
                images = [{"image_url": value} for value in request.reference_images]
                if request.first_frame:
                    images.insert(0, {"image_url": request.first_frame, "type": "first_frame"})
                if request.end_frame_url:
                    images.append({"image_url": request.end_frame_url, "type": "end_frame"})
                if images:
                    meta["image_list"] = images
                if request.reference_videos:
                    if len(request.reference_videos) != 1 or request.native_audio or mode == "4k" or request.duration_seconds > 10:
                        raise ValidationError("video reference requires one video, <=10s, std/pro, audio off")
                    meta["video_list"] = [{"video_url": request.reference_videos[0],
                                           "refer_type": "feature", "keep_original_sound": "no"}]
            else:
                if request.reference_images or request.reference_videos:
                    raise ValidationError("multi-source references require an Omni model")
                if request.first_frame:
                    body["image"] = request.first_frame
                if request.end_frame_url:
                    meta["image_tail"] = request.end_frame_url
                if request.negative_prompt:
                    meta["negative_prompt"] = request.negative_prompt
        body["metadata"] = meta
        return body

    async def _request(self, method, path, payload=None):
        if not self.api_key:
            raise AuthError("ORCAROUTER_API_KEY is required")
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.request(method, self.base_url + path,
                headers={"Authorization": f"Bearer {self.api_key}"}, json=payload)
        if response.status_code >= 400:
            # Don't retain response bodies that might echo prompts or credentials.
            raise classify_http_status(response.status_code)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderFailure("invalid JSON response") from exc
        if not isinstance(data, dict) or (data.get("code") not in (None, "success", 0)):
            raise ProviderFailure("unexpected video response envelope")
        return data

    async def create_task(self, request):
        data = await self._request("POST", "/video/generations", self.build_payload(request))
        rid = data.get("task_id") or data.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise ProviderFailure("submission returned no task ID; reconcile before retry")
        return VideoTask(provider=self.name, model=request.model, remote_job_id=rid)

    async def get_task(self, remote_job_id):
        data = await self._request("GET", "/video/generations/" + quote(remote_job_id, safe=""))
        inner = data.get("data")
        if not isinstance(inner, dict) or inner.get("task_id") != remote_job_id:
            raise ProviderFailure("query task ID mismatch or missing data")
        statuses = {"NOT_START": VideoTaskState.QUEUED, "SUBMITTED": VideoTaskState.QUEUED,
                    "IN_PROGRESS": VideoTaskState.RUNNING, "SUCCESS": VideoTaskState.SUCCEEDED,
                    "FAILURE": VideoTaskState.FAILED}
        return VideoTaskStatus(remote_job_id=remote_job_id,
            state=statuses.get(inner.get("status"), VideoTaskState.UNKNOWN),
            video_url=inner.get("result_url"), error_message=inner.get("fail_reason"))

    async def download_result(self, task, output_path: Path):
        if not task.video_url:
            raise IOError("successful task has no result URL")
        # Download with a separate unauthenticated client: never leak API key to CDN.
        return await download_video(_url(task.video_url), output_path, timeout=self.timeout)
