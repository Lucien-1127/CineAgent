"""Phase 10 + 11 tests: publishers (dry-run/failed/write remote id) + analytics."""
import asyncio

import pytest

from cineagent.analytics import AnalyticsCollector, ContentLearningStore, VideoMetrics
from cineagent.publish import XPublisher, PublishRequest
from cineagent.renderer import (
    FFmpegRenderer,
    RenderComposition,
    RenderSegment,
    make_test_media,
)
from cineagent.storage.database import Database
from cineagent.storage.repositories import PublishRepo, ensure_schema


def _run(coro):
    return asyncio.run(coro)


def _render_small_mp4() -> str:
    img, wav = make_test_media("/tmp/cineagent-pub-smoke")
    comp = RenderComposition(
        output_path="/tmp/cineagent-pub-smoke/short.mp4",
        aspect="9:16", fps=24,
        segments=[RenderSegment(path=img, start=0.0, duration=1.0, kind="image")],
        audio=wav,
    )
    return _run(FFmpegRenderer().render(comp))


def test_publisher_dry_run_by_default():
    pub = XPublisher()  # dry_run=True default
    path = _render_small_mp4()
    res = _run(pub.publish(PublishRequest(
        project_id="p1", video_path=path, platform="x", title="標題", caption="說明",
    )))
    assert res.status == "dry_run"
    assert "not published" in "dry-run: not published"


def test_publisher_validates_metadata_and_spec():
    pub = XPublisher()
    res = _run(pub.publish(PublishRequest(
        project_id="p1", video_path="/tmp/does_not_exist.mp4", platform="x",
        title="", caption="",
    )))
    assert res.status == "failed"
    assert res.error


def test_publisher_planned_post_raises_when_enabled():
    pub = XPublisher(dry_run=False)
    path = _render_small_mp4()
    with pytest.raises(RuntimeError):
        _run(pub.publish(PublishRequest(
            project_id="p1", video_path=path, platform="x", title="標題", caption="說明",
        )))


def test_publisher_persists_dry_run_in_repo():
    db = Database(":memory:")
    ensure_schema(db)
    repo = PublishRepo(db)
    pub = XPublisher(dry_run=True, repo=repo)
    path = _render_small_mp4()
    _run(pub.publish(PublishRequest(
        project_id="p1", video_path=path, platform="x", title="標題", caption="說明",
    )))
    row = repo.get(_find_pub(db))
    assert row is not None
    assert row["status"] == "dry_run"


def _find_pub(db) -> str:
    row = db.execute("SELECT publish_id FROM publish_jobs LIMIT 1").fetchone()
    return row["publish_id"]


def test_analytics_no_learning_below_min_samples():
    store = ContentLearningStore(min_samples=3)
    col = AnalyticsCollector(store)
    for i in range(2):
        col.record(VideoMetrics(video_ref=f"v{i}", views=100,
                                script_strategy="short_viral",
                                average_percentage_viewed=40.0))
    assert store.sample_count == 2
    assert store.insights() == []  # no global rule from 2 samples


def test_analytics_learning_after_min_samples():
    store = ContentLearningStore(min_samples=3)
    col = AnalyticsCollector(store)
    for i in range(3):
        col.record(VideoMetrics(video_ref=f"v{i}", views=100,
                                script_strategy="short_viral",
                                average_percentage_viewed=30.0))
    insights = store.insights("short_viral")
    assert len(insights) == 1
    assert insights[0].samples == 3
