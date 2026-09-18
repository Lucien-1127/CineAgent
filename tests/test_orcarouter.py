"""OrcaRouter wire-contract tests; no live API, keys or generation charges."""
import asyncio
import json

import httpx
import pytest

from cineagent.providers.base import AuthError, ProviderFailure, RateLimitError, ValidationError
from cineagent.providers.video.orcarouter import OrcaRouterVideoProvider, SEEDANCE
from cineagent.providers.video.schemas import VideoGenerationRequest, VideoTaskState


def request(model="kling/kling-v3", **kwargs):
    return VideoGenerationRequest(provider="orcarouter", model=model, prompt="product", **kwargs)


def test_kling_image_fields_and_4k_are_preserved():
    body = OrcaRouterVideoProvider().build_payload(request(image_url="https://example.com/first.png",
        end_frame_url="https://example.com/last.png", resolution="4k", duration_seconds=15))
    assert body["image"] == "https://example.com/first.png"
    assert body["metadata"]["image_tail"] == "https://example.com/last.png"
    assert body["metadata"]["mode"] == "4k"
    assert body["metadata"]["duration"] == "15"
    assert body["metadata"]["sound"] == "off"


def test_seedance_has_distinct_payload_and_current_model():
    body = OrcaRouterVideoProvider().build_payload(request(SEEDANCE,
        image_url="https://example.com/first.png", end_frame_url="https://example.com/last.png"))
    assert body["metadata"]["duration"] == 5
    assert body["metadata"]["generate_audio"] is False
    assert body["metadata"]["content"][1]["role"] == "end_frame"
    assert "image" not in body
    assert "prompt" not in body["metadata"]


def test_omni_reference_fields():
    body = OrcaRouterVideoProvider().build_payload(request("kling/kling-v3-omni",
        reference_images=["https://example.com/ref.png"],
        reference_videos=["https://example.com/ref.mp4"]))
    assert body["metadata"]["image_list"][0]["image_url"].endswith("ref.png")
    assert body["metadata"]["video_list"][0]["keep_original_sound"] == "no"


@pytest.mark.parametrize("kwargs", [
    {"model": "sora"}, {"model": "byteplus/seedance-2.0-fast"},
    {"model": "kling/kling-v2-master", "duration_seconds": 6},
    {"model": "kling/kling-v2-master", "resolution": "4k"},
    {"model": "kling/kling-v2-6", "native_audio": True},
    {"image_url": "/tmp/a.png"}, {"end_frame_url": "https://example.com/end.png"},
    {"reference_images": ["https://example.com/ref.png"]}, {"multi_shot": True},
    {"model": SEEDANCE, "duration_seconds": 3}, {"model": SEEDANCE, "resolution": "4k"},
])
def test_unsupported_parameters_fail_before_network(kwargs):
    with pytest.raises(ValidationError):
        OrcaRouterVideoProvider().build_payload(request(**kwargs))


def test_submit_and_poll_documented_envelopes():
    calls = []
    def handler(req):
        calls.append(req)
        assert req.headers["authorization"] == "Bearer test-fixture"
        if req.method == "POST":
            assert req.url.path == "/v1/video/generations"
            assert json.loads(req.content)["model"] == "kling/kling-v3"
            return httpx.Response(200, json={"id": "task_example", "status": "queued"})
        assert req.url.path == "/v1/video/generations/task_example"
        return httpx.Response(200, json={"code": "success", "data": {
            "task_id": "task_example", "status": "SUCCESS", "result_url": "https://example.com/video.mp4"}})
    provider = OrcaRouterVideoProvider(api_key="test-fixture", transport=httpx.MockTransport(handler))
    async def lifecycle():
        task = await provider.create_task(request())
        result = await provider.get_task(task.remote_job_id)
        assert result.state == VideoTaskState.SUCCEEDED
        assert result.video_url == "https://example.com/video.mp4"
    asyncio.run(lifecycle())
    assert len(calls) == 2


@pytest.mark.parametrize("status,expected", [(401, AuthError), (429, RateLimitError),
                                            (422, ValidationError), (502, ProviderFailure)])
def test_http_error_taxonomy(status, expected):
    provider = OrcaRouterVideoProvider(api_key="test-fixture", transport=httpx.MockTransport(
        lambda req: httpx.Response(status, text="do not retain raw response")))
    with pytest.raises(expected):
        asyncio.run(provider.create_task(request()))


def test_missing_task_id_is_uncertain_provider_failure():
    provider = OrcaRouterVideoProvider(api_key="test-fixture", transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"status": "queued"})))
    with pytest.raises(ProviderFailure):
        asyncio.run(provider.create_task(request()))


@pytest.mark.parametrize("status,expected", [("NOT_START", VideoTaskState.QUEUED),
    ("IN_PROGRESS", VideoTaskState.RUNNING), ("FAILURE", VideoTaskState.FAILED),
    ("new-state", VideoTaskState.UNKNOWN)])
def test_query_status_mapping(status, expected):
    provider = OrcaRouterVideoProvider(api_key="test-fixture", transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"code": "success", "data": {
            "task_id": "task_example", "status": status, "fail_reason": "detail"}})))
    assert asyncio.run(provider.get_task("task_example")).state == expected
