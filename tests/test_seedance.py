"""Seedance adapter: payload filtering, response mapping, HTTP error taxonomy."""
import asyncio

import httpx
import pytest

from cineagent.providers.base import (
    AuthError,
    ProviderFailure,
    RateLimitError,
    ValidationError,
)
from cineagent.providers.video.seedance import SeedanceVideoProvider
from cineagent.providers.video.schemas import VideoGenerationRequest, VideoTaskState


def _run(coro):
    return asyncio.run(coro)


def _provider(monkeypatch, handler, **kw):
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*a, **k):
        return orig(transport=transport, *a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return SeedanceVideoProvider(api_key="test", **kw)


def _req(**kw):
    base = dict(provider="seedance", model="doubao-seedance-2-5-260628", prompt="猫")
    base.update(kw)
    return VideoGenerationRequest(**base)


# ── payload building / filtering ──────────────────────────────────────
def test_text_to_video_payload():
    p = SeedanceVideoProvider(api_key="x")
    payload = p.build_payload(_req())
    assert payload["model"] == "doubao-seedance-2-5-260628"
    assert payload["content"] == [{"type": "text", "text": "猫"}]
    assert payload["duration"] == 5


def test_first_last_frame_roles():
    p = SeedanceVideoProvider(api_key="x")
    payload = p.build_payload(_req(image_url="http://x/f.png",
                                   end_frame_url="http://x/l.png"))
    roles = [(c["role"], c["image_url"]["url"]) for c in payload["content"]
             if c["type"] == "image_url"]
    assert roles == [("first_frame", "http://x/f.png"),
                     ("last_frame", "http://x/l.png")]


def test_reference_image_forwarded_for_2_5():
    p = SeedanceVideoProvider(api_key="x")
    payload = p.build_payload(_req(reference_images=["http://x/r.png"]))
    types = [c["type"] for c in payload["content"]]
    assert "image_url" in types
    ref = [c for c in payload["content"]
           if c["type"] == "image_url" and c.get("role") == "reference_image"]
    assert len(ref) == 1


def test_reference_image_dropped_for_1_0():
    p = SeedanceVideoProvider(api_key="x")
    payload = p.build_payload(_req(model="doubao-seedance-1-0-pro-250528",
                                   reference_images=["http://x/r.png"]))
    roles = [c.get("role") for c in payload["content"]]
    assert "reference_image" not in roles


def test_last_frame_dropped_for_1_0_fast():
    p = SeedanceVideoProvider(api_key="x")
    payload = p.build_payload(_req(model="doubao-seedance-1-0-pro-fast-251015",
                                   image_url="http://x/f.png",
                                   end_frame_url="http://x/l.png"))
    roles = [c.get("role") for c in payload["content"] if c["type"] == "image_url"]
    assert roles == ["first_frame"]  # last_frame silently dropped


def test_native_audio_gated_by_model():
    p = SeedanceVideoProvider(api_key="x")
    assert "generate_audio" in p.build_payload(_req(native_audio=True))
    p2 = SeedanceVideoProvider(api_key="x")
    payload = p2.build_payload(_req(model="doubao-seedance-1-0-pro-250528",
                                    native_audio=True))
    assert "generate_audio" not in payload


def test_unknown_model_raises():
    p = SeedanceVideoProvider(api_key="x")
    with pytest.raises(ValueError):
        p.build_payload(_req(model="nope"))


# ── response mapping ──────────────────────────────────────────────────
def test_parse_succeeded():
    p = SeedanceVideoProvider(api_key="x")
    st = p.parse_status({"id": "cgt-1", "status": "succeeded",
                         "content": {"video_url": "http://x/v.mp4",
                                     "last_frame_url": "http://x/l.png"},
                         "duration": 5})
    assert st.state == VideoTaskState.SUCCEEDED
    assert st.video_url == "http://x/v.mp4"
    assert st.last_frame_url == "http://x/l.png"


def test_parse_failed_with_error():
    p = SeedanceVideoProvider(api_key="x")
    st = p.parse_status({"id": "cgt-1", "status": "failed",
                         "error": {"code": "InvalidParameter", "message": "bad"}})
    assert st.state == VideoTaskState.FAILED
    assert st.error_code == "InvalidParameter"


# ── HTTP lifecycle + error taxonomy ───────────────────────────────────
def _handler(monkeypatch, status=200, body=None):
    def h(request):
        return httpx.Response(status, json=body)
    return _provider(monkeypatch, h)


def test_create_task_returns_remote_id(monkeypatch):
    p = _handler(monkeypatch, 200, {"id": "cgt-42", "status": "queued"})
    task = _run(p.create_task(_req()))
    assert task.remote_job_id == "cgt-42"


def test_get_task(monkeypatch):
    p = _handler(monkeypatch, 200, {"id": "cgt-42", "status": "succeeded",
                                    "content": {"video_url": "http://x/v.mp4"}})
    st = _run(p.get_task("cgt-42"))
    assert st.state == VideoTaskState.SUCCEEDED


@pytest.mark.parametrize("status,exc", [
    (401, AuthError), (403, AuthError), (429, RateLimitError),
    (422, ValidationError), (500, ProviderFailure),
])
def test_http_error_mapping(monkeypatch, status, exc):
    p = _handler(monkeypatch, status, {"error": {"code": "x", "message": "m"}})
    with pytest.raises(exc):
        _run(p.get_task("cgt-42"))


def test_download_missing_url_raises():
    p = SeedanceVideoProvider(api_key="x")
    from cineagent.providers.video.schemas import VideoTaskStatus
    st = VideoTaskStatus(remote_job_id="1", state=VideoTaskState.SUCCEEDED)
    with pytest.raises(IOError):
        _run(p.download_result(st, __import__("pathlib").Path("/tmp/x.mp4")))
