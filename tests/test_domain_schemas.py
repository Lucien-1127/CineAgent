"""Schema validation tests for canonical domain models."""
import pytest
from pydantic import ValidationError

from cineagent.domain import (
    GenerationJob,
    QualityMode,
    QAReport,
    Scene,
    ShotSize,
    ShotSpec,
    VideoProject,
    VisualBible,
    GenerationStrategy,
    JobState,
)


def test_video_project_defaults_and_fields():
    p = VideoProject(
        project_id="proj-1",
        topic="雨夜的霓虹城市",
    )
    assert p.platform.value == "shorts"
    assert p.aspect_ratio == "9:16"
    assert p.quality_mode == QualityMode.AUTO
    assert p.target_duration == 30.0
    assert p.budget_limit is None


def test_video_project_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        VideoProject(project_id="x", topic="t", not_a_field=1)


def test_video_project_budget_must_be_positive():
    with pytest.raises(ValidationError):
        VideoProject(project_id="x", topic="t", budget_limit=-5)


def test_shot_spec_required_fields_and_serialization():
    shot = ShotSpec(shot_id="sh-1", scene_id="sc-1")
    assert shot.duration == 0.0
    assert shot.shot_size == ShotSize.MEDIUM
    assert shot.generation_strategy == GenerationStrategy.GENERATED_IMAGE
    data = shot.model_dump()
    assert data["shot_id"] == "sh-1"
    assert data["scene_id"] == "sc-1"


def test_visual_bible_character_lookup():
    bible = VisualBible(
        project_id="p1",
        characters={
            "hero": {
                "char_id": "hero",
                "name": "林小雨",
                "wardrobe": "黑色皮衣",
            }
        },
    )
    assert bible.character("hero").wardrobe == "黑色皮衣"
    assert bible.character("nope") is None


def test_scene_belongs_to_script_package():
    from cineagent.domain import ScriptPackage, ScriptStrategy
    pkg = ScriptPackage(
        hook="第一句就抓住你",
        narration="完整旁白",
        scenes=[Scene(scene_id="sc-1", title="開場")],
        script_strategy=ScriptStrategy.SHORT_VIRAL,
    )
    assert len(pkg.scenes) == 1
    assert pkg.scenes[0].title == "開場"


def test_qa_report_pass_decision():
    r = QAReport(shot_id="sh-1", score=0.9, threshold=0.6, decision="pass")
    assert r.passed is True
    bad = QAReport(shot_id="sh-2", score=0.3)
    assert bad.passed is False


def test_generation_job_remote_id_durable():
    j = GenerationJob(
        job_id="job-1",
        provider="mock_video",
        model="mock-v2",
        remote_job_id="remote-abc",
        state=JobState.SUBMITTED,
    )
    # round-trip through dict keeps remote id (idempotency basis)
    restored = GenerationJob.model_validate(j.model_dump())
    assert restored.remote_job_id == "remote-abc"
    assert restored.state == JobState.SUBMITTED
