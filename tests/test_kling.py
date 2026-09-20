"""Kling adapter: JWT, payload filtering, response mapping, error taxonomy."""
import asyncio
import base64
import json

import httpx
import pytest

from cineagent.providers.base import AuthError, RateLimitError, ValidationError
from cineagent.providers.video.kling import KlingVideoProvider
from cineagent.providers.video.schemas import VideoGenerationRequest, VideoTaskState


def _run(coro):
    return asyncio.run(coro)


def _provider(monkeypatch, handler, **kw):
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*a, **k):
        return orig(transport=transport, *a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return KlingVideoProvider(access_key="ak", secret_key="sk", **kw)


def _req(**kw):
    base = dict(provider="kling", model="kling-v3", prompt="猫")
    base.update(kw)
    return VideoGenerationRequest(**base)


# ── JWT ───────────────────────────────────────────────────────────────
def test_jwt_is_three_segments_with_iss():
    p = KlingVideoProvider(access_key="ak", secret_key="sk")
    token = p._jwt()
    parts = token.split(".")
    assert len(parts) == 3
    payload = json.loads(base64.urlsafe_b64decode(parts[1] + "==").decode())
    assert payload["iss"] == "ak"
    assert payload["exp"] > payload["nbf"]


# ── payload building ──────────────────────────────────────────────────
def test_image2video_payload():
    p = KlingVideoProvider(access_key="ak", secret_key="sk")
    endpoint, body = p.build_payload(_req(image_url="http://x/f.jpg",
                                          end_frame_url="http://x/e.jpg"))
    assert endpoint == "image2video"
    assert body["image"] == "http://x/f.jpg"
    assert body["image_tail"] == "http://x/e.jpg"
    assert body["model_name"] == "kling-v3"


def test_text2video_payload():
    p = KlingVideoProvider(access_key="ak", secret_key="sk")
    endpoint, body = p.build_payload(_req())
    assert endpoint == "text2video"
    assert "image" not in body


def test_i2v_only_model_rejects_text():
    p = KlingVideoProvider(access_key="ak", secret_key="sk")
    with pytest.raises(ValueError):
        p.build_payload(_req(model="kling-v2-1"))  # no image => text2video


def test_sound_only_for_native_audio_models():
    p = KlingVideoProvider(access_key="ak", secret_key="sk")
    _, body = p.build_payload(_req(native_audio=True))  # kling-v3
    assert body["sound"] == "on"
    _, body2 = p.build_payload(_req(model="kling-v1", native_audio=True))
    assert "sound" not in body2


def test_duration_snaps_to_5_or_10():
    p = KlingVideoProvider(access_key="ak", secret_key="sk")
    _, b1 = p.build_payload(_req(duration_seconds=3))
    _, b2 = p.build_payload(_req(duration_seconds=8))
    assert b1["duration"] == "5"
    assert b2["duration"] == "10"


def test_unknown_model_raises():
    p = KlingVideoProvider(access_key="ak", secret_key="sk")
    with pytest.raises(ValueError):
        p.build_payload(_req(model="nope"))


# ── response mapping ──────────────────────────────────────────────────
def test_parse_succeed():
    p = KlingVideoProvider(access_key="ak", secret_key="sk")
    st = p.parse_status({"code": 0, "data": {
        "task_id": "t1", "task_status": "succeed",
        "task_result": {"videos": [{"id": "v1", "url": "http://x/v.mp4",
                                    "duration": "5"}]},
    }})
    assert st.state == VideoTaskState.SUCCEEDED
    assert st.video_url == "http://x/v.mp4"


def test_parse_failed():
    p = KlingVideoProvider(access_key="ak", secret_key="sk")
    st = p.parse_status({"code": 0, "data": {
        "task_id": "t1", "task_status": "failed",
        "task_status_msg": "moderation rejected",
    }})
    assert st.state == VideoTaskState.FAILED
    assert "moderation" in st.error_message


# ── HTTP lifecycle + errors ───────────────────────────────────────────
def test_create_task_returns_task_id(monkeypatch):
    p = _provider(monkeypatch, lambda r: httpx.Response(
        200, json={"code": 0, "data": {"task_id": "t9", "task_status": "submitted"}}))
    task = _run(p.create_task(_req()))
    assert task.remote_job_id == "t9"


@pytest.mark.parametrize("status,exc", [
    (401, AuthError), (429, RateLimitError), (422, ValidationError),
])
def test_http_error_mapping(monkeypatch, status, exc):
    p = _provider(monkeypatch, lambda r: httpx.Response(
        status, json={"code": status, "message": "err"}))
    with pytest.raises(exc):
        _run(p.get_task("t1"))
