"""Phase 7 tests: capability registry, model router, mock image/video providers."""
import asyncio

import pytest

from cineagent.providers.capability import (
    ModelRouter,
    NoCapableModelError,
    default_registry,
)
from cineagent.providers.image import ImageRequest
from cineagent.providers.image.mock import MockImageProvider
from cineagent.providers.video import VideoRequest
from cineagent.providers.video.mock import MockVideoProvider


def _run(coro):
    return asyncio.run(coro)


def test_capability_registry_has_mock_and_planned_vendors():
    reg = default_registry()
    assert reg.get("mock", "mock-video") is not None
    assert reg.get("mock", "mock-video").status == "implemented"
    assert reg.get("veo", "veo-video").status == "planned"


def test_model_router_selects_feasible_mock():
    router = ModelRouter(default_registry())
    chain = router.select(
        required_caps={"image_to_video"}, duration=8.0, aspect="9:16",
    )
    assert ("mock", "mock-video") in chain
    assert chain[0] == ("mock", "mock-video")


def test_model_router_respects_budget():
    router = ModelRouter(default_registry())
    # mock cost 0 <= budget
    assert router.select(
        required_caps={"image_to_video"}, duration=8.0, budget=0.1,
    )[0] == ("mock", "mock-video")


def test_model_router_raises_when_no_capability():
    router = ModelRouter(default_registry())
    with pytest.raises(NoCapableModelError):
        router.select(required_caps={"audio_generation", "unknown_cap_x"},
                      duration=8.0)


def test_model_router_excludes_planned_by_default():
    router = ModelRouter(default_registry())
    # only mock is feasible; planned vendors are excluded -> still picks mock
    chain = router.select(required_caps={"image_to_video"}, duration=8.0)
    assert all(prov != "veo" for prov, _ in chain)


def test_video_provider_submit_is_idempotent():
    p = MockVideoProvider()
    req = VideoRequest(prompt="城市下雨", duration=8.0, idempotency_key="shot-1")
    ref1 = _run(p.submit(req))
    ref2 = _run(p.submit(req))
    assert ref1.remote_job_id == ref2.remote_job_id
    assert len(p._jobs) == 1  # created once => no double billing


def test_video_provider_poll_lifecycle():
    p = MockVideoProvider()
    req = VideoRequest(prompt="城市下雨", duration=8.0, idempotency_key="shot-2")
    ref = _run(p.submit(req))
    assert _run(p.poll(ref.remote_job_id)).state == "generating"
    p.complete(ref.remote_job_id, uri="file://out.mp4")
    res = _run(p.poll(ref.remote_job_id))
    assert res.state == "succeeded"
    assert res.uri == "file://out.mp4"


def test_image_provider_generates_uri():
    p = MockImageProvider(out_dir="/tmp/cineagent-mock-images-test")
    res = _run(p.generate(ImageRequest(prompt="城市夜景 霓虹")))
    assert res.uri.endswith(".png")
    assert res.provider == "mock-image"
