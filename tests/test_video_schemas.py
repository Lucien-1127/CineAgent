"""Unified schema validation + unsupported-parameter filtering."""
import pytest
from pydantic import ValidationError

from cineagent.providers.video.schemas import (
    VideoGenerationRequest,
    VideoTaskState,
    VideoTaskStatus,
)


def test_request_defaults_and_validation():
    req = VideoGenerationRequest(provider="kling", model="kling-v3", prompt="猫")
    assert req.duration_seconds == 5
    assert req.aspect_ratio == "9:16"
    assert req.features() == ["text_to_video"]


def test_request_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        VideoGenerationRequest(provider="k", model="m", prompt="p", bogus=1)


def test_features_detects_image_and_last_frame():
    req = VideoGenerationRequest(
        provider="k", model="m", prompt="p", image_url="http://x/f.png",
        end_frame_url="http://x/l.png",
    )
    assert "image_to_video" in req.features()
    assert "first_frame" in req.features()
    assert "last_frame" in req.features()


def test_features_detects_references_and_audio():
    req = VideoGenerationRequest(
        provider="k", model="m", prompt="p",
        reference_images=["http://x/r.png"], reference_videos=["http://x/v.mp4"],
        audio_url="http://x/a.wav", native_audio=True,
    )
    feats = set(req.features())
    assert {"reference_image", "reference_video", "reference_audio",
            "audio_generation"} <= feats


def test_first_frame_alias():
    req = VideoGenerationRequest(provider="k", model="m", prompt="p",
                                 start_frame_url="http://x/f.png")
    assert req.first_frame == "http://x/f.png"
    assert req.image_url is None


def test_task_status_terminal():
    assert VideoTaskStatus(remote_job_id="1", state=VideoTaskState.SUCCEEDED).terminal
    assert VideoTaskStatus(remote_job_id="1", state=VideoTaskState.RUNNING).terminal is False
