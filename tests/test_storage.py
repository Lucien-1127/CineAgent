"""Storage / state-recovery / idempotency / cost ledger tests (SQLite + WAL)."""
import pytest

from cineagent.domain import GenerationJob, JobState, VideoProject, UsageEvent, Asset, AssetSource, AssetType
from cineagent.storage.database import Database
from cineagent.storage.repositories import (
    AssetRepo,
    JobRepo,
    ProjectRepo,
    QARepo,
    ShotRepo,
    UsageRepo,
    ensure_schema,
)


@pytest.fixture
def db():
    d = Database(":memory:")
    ensure_schema(d)
    yield d
    d.close()


def test_schema_creates_all_tables(db):
    tables = {
        r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for t in ("projects", "scenes", "shots", "assets", "jobs",
              "usage_events", "qa_reports", "publish_jobs"):
        assert t in tables


def test_shot_state_recovery(db):
    repo = ShotRepo(db)
    repo.upsert({
        "shot_id": "sh-1", "project_id": "p1", "scene_id": "sc-1",
        "state": "generating", "start_time": 0.0, "end_time": 3.2,
    })
    got = repo.get("sh-1")
    assert got["state"] == "generating"
    # crash → on restart, state is read back as generating (NOT complete)
    assert got["state"] != "completed"
    repo.set_state("sh-1", "succeeded")
    assert repo.get("sh-1")["state"] == "succeeded"


def test_job_idempotency_by_remote_id(db):
    repo = JobRepo(db)
    j1 = GenerationJob(
        job_id="job-1", project_id="p1", shot_id="sh-1",
        provider="mock", model="m", remote_job_id="remote-xyz",
        state=JobState.SUBMITTED,
    )
    repo.upsert(j1)
    # Simulate resume after crash: re-discover by remote id → same job, not new billing unit
    found = repo.get_by_remote("remote-xyz")
    assert found is not None
    assert found.job_id == "job-1"


def test_job_list_for_shot(db):
    repo = JobRepo(db)
    for i in range(3):
        repo.upsert(GenerationJob(
            job_id=f"job-{i}", shot_id="sh-9", provider="mock", model="m",
            remote_job_id=f"r{i}", state=JobState.SUBMITTED,
        ))
    assert len(repo.get_for_shot("sh-9")) == 3


def test_cost_ledger_aggregations(db):
    repo = UsageRepo(db)
    base = dict(provider="mock_video", model="mv-2", project_id="p1")
    repo.record(UsageEvent(event_id="e1", operation="video", video_seconds=4.0,
                           estimated_cost=0.2, actual_cost=0.25, **base))
    repo.record(UsageEvent(event_id="e2", operation="video", video_seconds=6.0,
                           estimated_cost=0.3, actual_cost=0.35, **base))
    repo.record(UsageEvent(event_id="e3", operation="image", image_count=1,
                           estimated_cost=0.02, actual_cost=0.02, status="failed",
                           provider="mock_image", model="mi-1", project_id="p1"))

    assert repo.project_total("p1") == pytest.approx(0.25 + 0.35 + 0.02)
    assert repo.project_estimated("p1") == pytest.approx(0.2 + 0.3 + 0.02)
    assert repo.cost_by_provider("p1")["mock_video"] == pytest.approx(0.6)
    assert repo.cost_by_model("p1")["mv-2"] == pytest.approx(0.6)
    assert repo.cost_by_stage("p1")["video"] == pytest.approx(0.6)
    assert repo.failed_cost("p1") == pytest.approx(0.02)


def test_asset_hash_dedup_and_reuse_count(db):
    repo = AssetRepo(db)
    a1 = Asset(asset_id="a-1", source=AssetSource.GENERATED, type=AssetType.VIDEO,
               uri="/tmp/a.mp4", hash="abc123")
    repo.upsert(a1)
    dup = repo.find_by_hash("abc123")
    assert dup is not None and dup.asset_id == "a-1"
    repo.increment_reuse("a-1")
    assert repo.find_by_hash("abc123").reuse_count == 1


def test_project_upsert_and_read(db):
    repo = ProjectRepo(db)
    p = VideoProject(project_id="p1", topic="賽博朋克台北", budget_limit=5.0)
    repo.upsert(p)
    got = repo.get("p1")
    assert got.topic == "賽博朋克台北"
    assert got.budget_limit == 5.0
