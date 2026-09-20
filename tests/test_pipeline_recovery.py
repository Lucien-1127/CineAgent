"""Regression scenarios for paid-task recovery and truthful completion."""
import asyncio
from pathlib import Path

import httpx
import pytest

from cineagent import cli
from cineagent.domain import PipelineRunState
from cineagent.orchestration import VideoPipelineRunner, plan_segments
from cineagent.providers.base import ProviderFailure
from cineagent.providers.video.schemas import VideoTaskStatus, VideoTaskState
from cineagent.storage.run_lock import run_lock
from conftest import FakeVideoProvider


def setup(tmp_path, provider_class=FakeVideoProvider, total=5):
    provider = provider_class(str(tmp_path / "source"))
    state = PipelineRunState(run_id="unique-run", objective="product",
                             provider=provider.name, model="fake-model")
    plans = plan_segments(total, 5, overlap_seconds=0, provider=provider.name, model=state.model)
    for plan in plans:
        plan.start_frame_source = "keyframe"
    runner = VideoPipelineRunner(provider, str(tmp_path / "out"), poll_interval=0)
    return provider, state, plans, runner


def run(runner, state, plans, stitch=False):
    return asyncio.run(runner.run(state, plans, stitch=stitch))


def test_crash_after_submit_recovers_saved_handle_without_resubmission(tmp_path):
    class Crash(BaseException):
        pass
    class Crashing(FakeVideoProvider):
        async def get_task(self, rid):
            raise Crash()
    provider, state, plans, runner = setup(tmp_path, Crashing)
    with pytest.raises(Crash):
        run(runner, state, plans)
    saved = PipelineRunState.from_file(runner.state_file)
    assert saved.segment(0).remote_job_id == "job-1"
    restarted = FakeVideoProvider(str(tmp_path / "source"))
    runner.provider = restarted
    run(runner, saved, plans)
    assert restarted.create_calls == []
    assert saved.completed == [0]


@pytest.mark.parametrize("failure", [ProviderFailure("502"), httpx.ReadTimeout("timeout"),
                                    ValueError("invalid response JSON")])
def test_ambiguous_submission_never_replayed(tmp_path, failure):
    class Ambiguous(FakeVideoProvider):
        async def create_task(self, request):
            self.create_calls.append(0)
            raise failure
    provider, state, plans, runner = setup(tmp_path, Ambiguous)
    run(runner, state, plans)
    assert state.segment(0).status == "submission_unknown"
    saved = PipelineRunState.from_file(runner.state_file)
    run(runner, saved, plans)
    assert len(provider.create_calls) == 1
    assert saved.current_stage == "BLOCKED"


def test_crash_before_task_id_cannot_blindly_resubmit(tmp_path):
    provider, state, plans, runner = setup(tmp_path)
    state.ensure_segment(0).status = "submitting"
    run(runner, state, plans)
    assert not provider.create_calls
    assert state.current_stage == "BLOCKED"


def test_poll_timeout_then_resume_queries_existing_job(tmp_path):
    class Slow(FakeVideoProvider):
        async def get_task(self, rid):
            return VideoTaskStatus(remote_job_id=rid, state=VideoTaskState.RUNNING)
    provider, state, plans, runner = setup(tmp_path, Slow)
    runner.poll_timeout = 0
    run(runner, state, plans)
    assert state.current_stage == "INCOMPLETE"
    assert state.segment(0).remote_job_id
    restarted = FakeVideoProvider(str(tmp_path / "source"))
    runner.provider = restarted
    run(runner, state, plans)
    assert not restarted.create_calls
    assert state.completed == [0]


def test_poll_transient_error_retries_query_not_submit(tmp_path):
    class Transient(FakeVideoProvider):
        calls = 0
        async def get_task(self, rid):
            self.calls += 1
            if self.calls == 1:
                raise ProviderFailure("503")
            return await super().get_task(rid)
    provider, state, plans, runner = setup(tmp_path, Transient)
    run(runner, state, plans)
    assert provider.create_calls == [0]
    assert provider.calls == 2
    assert state.completed == [0]


def test_partial_download_recovers_without_new_paid_job(tmp_path):
    class Interrupted(FakeVideoProvider):
        async def download_result(self, task, path):
            path.write_bytes(b"partial")
            raise httpx.ReadError("connection lost")
    provider, state, plans, runner = setup(tmp_path, Interrupted)
    run(runner, state, plans)
    assert state.current_stage == "INCOMPLETE"
    assert not state.segment(0).is_complete
    assert not (runner.workdir / "segment_000.mp4").exists()
    restarted = FakeVideoProvider(str(tmp_path / "source"))
    runner.provider = restarted
    run(runner, state, plans)
    assert state.segment(0).is_complete
    assert not restarted.create_calls


def test_remote_success_without_local_file_downloads_before_completion(tmp_path):
    provider, state, plans, runner = setup(tmp_path)
    seg = state.ensure_segment(0)
    source = tmp_path / "remote.mp4"
    source.write_bytes(b"video")
    seg.status, seg.output_url = "succeeded", str(source)
    run(runner, state, plans)
    assert state.completed == [0]
    assert not provider.create_calls


def test_remote_failed_task_is_not_resubmitted(tmp_path):
    provider, state, plans, runner = setup(tmp_path)
    provider.fail_next = True
    run(runner, state, plans)
    assert state.current_stage == "FAILED"
    provider.fail_next = True
    run(runner, state, plans)
    assert provider.create_calls == [0]


def test_partial_success_does_not_stitch(tmp_path, monkeypatch):
    class SecondFails(FakeVideoProvider):
        async def get_task(self, rid):
            if rid == "job-2":
                return VideoTaskStatus(remote_job_id=rid, state=VideoTaskState.FAILED)
            return await super().get_task(rid)
    provider, state, plans, runner = setup(tmp_path, SecondFails, total=10)
    async def forbidden(*args):
        pytest.fail("must not stitch incomplete run")
    monkeypatch.setattr(runner, "_stitch", forbidden)
    run(runner, state, plans, stitch=True)
    assert state.completed == [0]
    assert state.current_stage == "FAILED"
    assert not state.final_path


def test_stitch_error_is_not_success_and_old_final_not_advertised(tmp_path, monkeypatch):
    provider, state, plans, runner = setup(tmp_path)
    (runner.workdir / "final.mp4").write_bytes(b"stale")
    async def fail(*args):
        raise RuntimeError("encoder failure")
    monkeypatch.setattr(runner, "_stitch", fail)
    run(runner, state, plans, stitch=True)
    assert state.current_stage == "FAILED"
    assert state.final_path is None
    assert "encoder failure" in state.last_error


def test_real_chaining_blocked_before_any_paid_submission(tmp_path):
    class Remote(FakeVideoProvider):
        requires_public_media = True
    provider, state, plans, runner = setup(tmp_path, Remote, total=10)
    plans[1].start_frame_source = "previous_last_frame"
    run(runner, state, plans)
    assert not provider.create_calls
    assert state.current_stage == "BLOCKED"


def test_resume_extracts_image_not_mp4_for_next_segment(tmp_path, monkeypatch):
    provider, state, plans, runner = setup(tmp_path, total=10)
    seg = state.ensure_segment(0)
    clip = tmp_path / "complete.mp4"
    clip.write_bytes(b"video")
    seg.local_path, seg.status = str(clip), "succeeded"
    plans[1].start_frame_source = "previous_last_frame"
    image = tmp_path / "tail.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(runner, "_tail_frame", lambda previous: str(image))
    run(runner, state, plans)
    assert state.segment(1).image_url == str(image)
    assert provider.create_calls == [1]


def test_frame_extraction_failure_blocks_and_is_persisted(tmp_path, monkeypatch):
    provider, state, plans, runner = setup(tmp_path, total=10)
    plans[1].start_frame_source = "previous_last_frame"
    monkeypatch.setattr(runner, "_tail_frame", lambda previous: None)
    run(runner, state, plans)
    saved = PipelineRunState.from_file(runner.state_file)
    assert saved.seam_failures
    assert saved.current_stage == "BLOCKED"
    assert provider.create_calls == [0]


def test_cli_resume_restores_provider_plan_and_inputs(tmp_path, monkeypatch):
    provider, state, plans, runner = setup(tmp_path)
    run(runner, state, plans)
    selected = []
    monkeypatch.setattr(cli, "_make_provider", lambda name: selected.append(name) or provider)
    async def inspect(self, saved, restored, **kwargs):
        assert self.workdir == Path(saved.workdir)
        assert saved.objective == "product"
        assert restored == plans
        assert saved.segment(0).prompt == "product"
        saved.current_stage = "FAILED"
        return saved
    monkeypatch.setattr(VideoPipelineRunner, "run", inspect)
    assert cli.main(["--resume", runner.state_file]) == 1
    assert selected == ["fake-video"]
    assert cli.main(["--resume", runner.state_file, "--video-provider", "kling"]) == 1
    assert selected == ["fake-video"]


def test_missing_resume_does_not_construct_provider(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_make_provider", lambda _: pytest.fail("must not create provider"))
    assert cli.main(["--resume", str(tmp_path / "missing.json")]) == 1
    assert "resume file does not exist" in capsys.readouterr().err


def test_atomic_checkpoint_failure_preserves_previous_file(tmp_path, monkeypatch):
    import cineagent.domain.pipeline as module
    state = PipelineRunState(run_id="old")
    path = tmp_path / "state.json"
    state.to_file(str(path))
    state.run_id = "new"
    monkeypatch.setattr(module.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        state.to_file(str(path))
    assert PipelineRunState.from_file(str(path)).run_id == "old"


def test_state_lock_refuses_concurrent_writer_and_releases(tmp_path):
    path = tmp_path / "run.lock"
    with run_lock(path):
        with pytest.raises(RuntimeError):
            with run_lock(path):
                pass
    with run_lock(path):
        pass


def test_short_tail_uses_legal_generated_duration():
    plans = plan_segments(10.1, 10, overlap_seconds=0, min_segment_duration=5,
                          allowed_durations=[5, 10])
    assert plans[-1].duration_seconds == 0.1
    assert plans[-1].generation_duration_seconds == 5


@pytest.mark.parametrize("argument", ["nan", "inf", "-1", "0"])
def test_cli_invalid_duration_rejected_before_provider(argument, monkeypatch):
    monkeypatch.setattr(cli, "_make_provider", lambda _: pytest.fail("no API call expected"))
    assert cli.main(["--topic", "test", "--total-duration", argument, "--plan-only"]) == 1


def test_native_audio_not_silently_discarded_after_paid_generation(tmp_path):
    provider, state, plans, runner = setup(tmp_path)
    state.ensure_segment(0).native_audio = True
    run(runner, state, plans, stitch=True)
    assert state.current_stage == "BLOCKED"
    assert not provider.create_calls


def test_run_identity_separates_submission_keys(tmp_path):
    provider, state, plans, runner = setup(tmp_path)
    first = runner._ensure(plans[0], state).idempotency_key
    other = PipelineRunState(run_id="different-run", provider=state.provider, model=state.model)
    second = runner._ensure(plans[0], other).idempotency_key
    assert first != second


def test_live_local_image_blocked_before_submission(tmp_path):
    class Remote(FakeVideoProvider):
        requires_public_media = True
    provider, state, plans, runner = setup(tmp_path, Remote)
    state.ensure_segment(0).image_url = "/tmp/first.png"
    run(runner, state, plans)
    assert state.current_stage == "BLOCKED"
    assert not provider.create_calls


def test_mock_process_restart_recovers_completed_source(tmp_path):
    from cineagent.providers.video.mock_generation import MockGenerationProvider
    rid = "1234567890abcdef"
    (tmp_path / f"{rid}.mp4").write_bytes(b"offline-source")
    provider = MockGenerationProvider(out_dir=str(tmp_path))
    result = asyncio.run(provider.get_task(rid))
    assert result.state == VideoTaskState.SUCCEEDED
    assert result.video_url == str(tmp_path / f"{rid}.mp4")


def test_cli_mock_provider_uses_unique_temp_storage():
    first = cli._make_provider("mock")
    second = cli._make_provider("mock")
    assert first.out_dir != second.out_dir


def test_cli_resume_rejects_mixed_aspect_ratios(tmp_path, monkeypatch, capsys):
    provider, state, plans, runner = setup(tmp_path, total=10)
    run(runner, state, plans)
    saved = PipelineRunState.from_file(runner.state_file)
    saved.segment(1).aspect_ratio = "16:9"
    saved.to_file(runner.state_file)
    monkeypatch.setattr(cli, "_make_provider", lambda _: pytest.fail("must not construct provider"))
    assert cli.main(["--resume", runner.state_file]) == 1
    assert "same aspect ratio" in capsys.readouterr().err
