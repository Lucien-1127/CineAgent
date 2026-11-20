"""HTTP providers for CineAgent v4 (stdlib only — no httpx dependency).

Three clients, all built on :func:`request_json`:

* :class:`OrcaVideo`   — ``POST /v1/video/generations`` submit + poll + download
* :class:`OrcaImages`  — ``POST /v1/images/generations`` (imagen only)
* :class:`OpenRouterVideo` — ``POST /api/v1/videos`` async API
* :class:`Chat`        — OpenAI-compatible chat completions (text + vision)

Retry policy is intentionally conservative: 429/5xx retried with exponential
backoff, 4xx surfaced immediately with the provider's own message (the routers
return actionable text such as ``only imagen models are supported``).
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 120
MAX_ATTEMPTS = 4
BACKOFF_BASE = 2.0


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body

    @property
    def retryable(self) -> bool:
        return self.status in (408, 409, 425, 429) or (self.status or 0) >= 500


def _post(url: str, payload: dict, api_key: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json",
                 "User-Agent": "cineagent/4.0"},
    )
    return _send(req, timeout)


def _get(url: str, api_key: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}",
                 "Accept": "application/json",
                 "User-Agent": "cineagent/4.0"},
    )
    return _send(req, timeout)


def _send(req: urllib.request.Request, timeout: int) -> dict:
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:800]
            err = ProviderError(f"HTTP {exc.code}: {body}", exc.code, body)
            if not err.retryable or attempt == MAX_ATTEMPTS - 1:
                raise err from None
            last = err
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt == MAX_ATTEMPTS - 1:
                raise ProviderError(f"network error: {exc}") from None
        time.sleep(BACKOFF_BASE ** attempt)
    raise ProviderError(f"request failed: {last}")


def image_arg(path_or_url: str) -> str:
    """Return what Kling/Imagen accept for an image input.

    Remote URLs pass through; local files become raw base64 (Kling documents
    "URL or raw base64 (no ``data:`` prefix)" for ``image_list``).
    """
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    path = Path(path_or_url)
    if not path.exists():
        raise ProviderError(f"image not found: {path}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def save_image(payload: dict, dest: Path) -> Path:
    """Persist either ``b64_json`` or ``url`` payloads returned by image APIs."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    items = payload.get("data") or []
    if not items:
        raise ProviderError(f"no image data in response: {str(payload)[:200]}")
    first = items[0]
    if first.get("b64_json"):
        dest.write_bytes(base64.b64decode(first["b64_json"]))
        return dest
    if first.get("url"):
        req = urllib.request.Request(first["url"], headers={"User-Agent": "cineagent/4.0"})
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            dest.write_bytes(resp.read())
        return dest
    raise ProviderError(f"unsupported image payload keys: {list(first)}")


# ── video ────────────────────────────────────────────────────────────────────

class OrcaVideo:
    """OrcaRouter async video: submit → poll → download."""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def build_payload(
        self,
        prompt: str,
        *,
        first_frame: str | None = None,
        last_frame: str | None = None,
        image_list: list[dict] | None = None,
        video_list: list[dict] | None = None,
        mode: str = "pro",
        aspect_ratio: str = "16:9",
        duration: int = 5,
        negative_prompt: str = "",
        cfg_scale: float | None = None,
        sound: str = "off",
    ) -> dict:
        """Assemble the documented Kling body.

        Contract enforced here (mirrors docs.orcarouter.ai/kling-video):
        * ``image`` is the first frame, ``metadata.image_tail`` the last frame.
        * ``image_list``/``video_list`` are Omni-only surfaces.
        * end frame requires a first frame.
        * ``image_list`` items use ``type`` = ``first_frame`` / ``end_frame``.
        * ``video_list`` forces ``sound: off``.
        """
        if last_frame and not first_frame:
            raise ProviderError("end frame supplied without a first frame; Kling rejects end-only anchoring")
        metadata: dict[str, Any] = {
            "mode": mode,
            "aspect_ratio": aspect_ratio,
            "duration": str(int(duration)),
        }
        if negative_prompt:
            metadata["negative_prompt"] = negative_prompt[:2500]
        if cfg_scale is not None:
            metadata["cfg_scale"] = max(0.0, min(1.0, float(cfg_scale)))
        if sound:
            metadata["sound"] = sound

        payload: dict[str, Any] = {"model": self.model, "prompt": prompt}
        if first_frame:
            payload["image"] = image_arg(first_frame)
        if last_frame:
            metadata["image_tail"] = image_arg(last_frame)
        if image_list:
            metadata["image_list"] = [
                {"image_url": image_arg(item["image_url"]), **({"type": item["type"]} if item.get("type") else {})}
                for item in image_list
            ]
        if video_list:
            metadata["video_list"] = video_list
            metadata["sound"] = "off"
        payload["metadata"] = metadata
        return payload

    def submit(self, payload: dict) -> str:
        data = _post(self.base_url + "/video/generations", payload, self.api_key)
        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise ProviderError(f"submit returned no task id: {str(data)[:200]}")
        return str(task_id)

    def poll(self, task_id: str, timeout: int = 900, interval: float = 6.0) -> dict:
        url = f"{self.base_url}/video/generations/{task_id}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = _get(url, self.api_key)
            body = data.get("data", data)
            status = str(body.get("status", "")).upper()
            if status == "SUCCESS":
                return body
            if status == "FAILURE":
                raise ProviderError(f"video task failed: {body.get('fail_reason') or body}")
            time.sleep(interval)
        raise ProviderError(f"video task {task_id} timed out after {timeout}s")

    def render(self, payload: dict, dest: Path, timeout: int = 900) -> Path:
        body = self.poll(self.submit(payload), timeout=timeout)
        url = body.get("result_url") or body.get("video_url")
        if not url:
            raise ProviderError(f"SUCCESS without result_url: {str(body)[:200]}")
        return download(url, dest)


class OpenRouterVideo:
    """OpenRouter async videos API (``/api/v1/videos``)."""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def build_payload(self, prompt: str, *, duration: int = 8,
                      aspect_ratio: str = "16:9", resolution: str = "720p",
                      first_frame: str | None = None,
                      last_frame: str | None = None) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "duration": int(duration),
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }
        if first_frame:
            payload["start_frame"] = image_arg(first_frame)
        if last_frame:
            if not first_frame:
                raise ProviderError("end frame supplied without a start frame")
            payload["end_frame"] = image_arg(last_frame)
        return payload

    def submit(self, payload: dict) -> str:
        data = _post(self.base_url + "/videos", payload, self.api_key)
        job = data.get("id")
        if not job:
            raise ProviderError(f"submit returned no job id: {str(data)[:200]}")
        return str(job)

    def poll(self, job_id: str, timeout: int = 900, interval: float = 10.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = _get(f"{self.base_url}/videos/{job_id}", self.api_key)
            status = str(data.get("status", "")).lower()
            if status == "completed":
                return data
            if status in ("failed", "cancelled", "expired"):
                raise ProviderError(f"video job {job_id} ended: {status} {data.get('error', '')}")
            time.sleep(interval)
        raise ProviderError(f"video job {job_id} timed out after {timeout}s")

    def render(self, payload: dict, dest: Path, timeout: int = 900) -> Path:
        job_id = self.submit(payload)
        body = self.poll(job_id, timeout=timeout)
        url = None
        for candidate in (body.get("urls") or []) + (body.get("unsigned_urls") or []):
            url = candidate
            break
        if not url:
            url = f"{self.base_url}/videos/{job_id}/content"
        return download(url, dest, api_key=self.api_key if url.endswith("/content") else None)


def download(url: str, dest: Path, api_key: str | None = None, timeout: int = 300) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "cineagent/4.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dest.write_bytes(resp.read())
    return dest


# ── images ───────────────────────────────────────────────────────────────────

class OrcaImages:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str, dest: Path, *, n: int = 1,
                 aspect_ratio: str = "16:9", size: str | None = None,
                 negative_prompt: str = "", reference_image: str | None = None) -> Path:
        payload: dict[str, Any] = {"model": self.model, "prompt": prompt, "n": n,
                                   "aspect_ratio": aspect_ratio}
        if size:
            payload["size"] = size
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        data = _post(self.base_url + "/images/generations", payload, self.api_key, timeout=240)
        return save_image(data, dest)


class OpenRouterImages:
    """Image generation over OpenRouter chat completions (``modalities``).

    OpenRouter exposes image output on chat models (gemini-*-image, gpt-*-image)
    rather than an ``/images/generations`` route; output arrives as base64 data
    URIs inside ``choices[0].message.images``. Requires >= $1 key balance.
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str, dest: Path, *, n: int = 1,
                 aspect_ratio: str = "16:9", size: str | None = None,
                 negative_prompt: str = "", reference_image: str | None = None) -> Path:
        text = prompt
        if aspect_ratio:
            text += f"\nFraming: {aspect_ratio} aspect ratio."
        if negative_prompt:
            text += f"\nAvoid: {negative_prompt}"
        content: list[dict] = [{"type": "text", "text": text}]
        if reference_image:
            content.append(image_content(reference_image))
        payload = {"model": self.model,
                   "messages": [{"role": "user", "content": content}],
                   "modalities": ["image", "text"]}
        data = _post(self.base_url + "/chat/completions", payload, self.api_key, timeout=300)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError):
            raise ProviderError(f"malformed image response: {str(data)[:300]}") from None
        images = message.get("images") or []
        url = ""
        if images:
            first = images[0]
            url = (first.get("image_url") or {}).get("url") if isinstance(first, dict) else str(first)
        if not url:
            raise ProviderError(f"model returned no image: {str(message)[:200]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.startswith("data:"):
            import base64 as _b64
            dest.write_bytes(_b64.b64decode(url.split(",", 1)[1]))
        else:
            download(url, dest)
        return dest


class MultiImages:
    """Try every healthy image route in order; report why each one failed."""

    def __init__(self, decisions: list):
        self.clients = []
        for decision in decisions:
            cls = OpenRouterImages if decision.spec.provider == "openrouter" else OrcaImages
            self.clients.append((f"{decision.spec.provider}:{decision.spec.id}",
                                 cls(decision.base_url, decision.api_key, decision.spec.id)))

    def generate(self, prompt: str, dest: Path, **kwargs) -> Path:
        failures: list[str] = []
        for name, client in self.clients:
            try:
                return client.generate(prompt, dest, **kwargs)
            except ProviderError as exc:
                failures.append(f"{name}: {exc}")
                continue
        raise ProviderError("all image routes failed:\n  " + "\n  ".join(failures))


# ── chat / vision ────────────────────────────────────────────────────────────

class Chat:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def complete(self, messages: list[dict], *, temperature: float = 0.4,
                 max_tokens: int = 2048, json_mode: bool = False) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = _post(self.base_url + "/chat/completions", payload, self.api_key, timeout=240)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError):
            raise ProviderError(f"malformed chat response: {str(data)[:300]}") from None
        return (message.get("content") or "").strip()


def image_content(path_or_url: str) -> dict:
    if path_or_url.startswith(("http://", "https://", "data:")):
        url = path_or_url
    else:
        mime = mimetypes.guess_type(path_or_url)[0] or "image/jpeg"
        url = f"data:{mime};base64," + base64.b64encode(Path(path_or_url).read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": url}}
