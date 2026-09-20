"""Checkpointed video jobs. Uncertain paid submissions are never auto-replayed."""
from __future__ import annotations

import asyncio
import math
import shutil
import time
from pathlib import Path
from typing import Awaitable, Callable, List, Optional
from urllib.parse import urlsplit

import httpx

from ..domain.pipeline import PipelineRunState, SegmentState
from ..providers.base import (AuthError, ProviderError, ProviderFailure,
                              RateLimitError, TimeoutError, ValidationError)
from ..providers.video.generation import GenerationProvider
from ..providers.video.schemas import VideoGenerationRequest, VideoTaskState, VideoTaskStatus
from ..media.ffmpeg import MediaCommandError, MediaToolMissing, probe_video
from .planner import SegmentPlan
from .stitching import extract_last_frame_safe, stitch_segments


class SegmentError(Exception):
    """Confirmed task failure; no automatic paid re-generation."""


class BlockerError(Exception):
    """Stop until an operator resolves the blocking condition."""


class RecoverableError(Exception):
    """Existing remote job can be queried/downloaded again without submission."""


def public_media_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in ("https", "http") and bool(parsed.hostname)


class VideoPipelineRunner:
    def __init__(self, provider: GenerationProvider, workdir: str,
                 poll_interval: float = 5.0, poll_timeout: float = 600.0,
                 state_file: Optional[str] = None,
                 frame_publisher: Optional[Callable[[str], Awaitable[str]]] = None) -> None:
        self.provider = provider
        self.workdir = Path(workdir).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.state_file = state_file or str(self.workdir / "state.json")
        self.frame_publisher = frame_publisher

    def _save(self, state):
        self._sync_lists(state)
        state.to_file(self.state_file)

    @property
    def _remote(self):
        return getattr(self.provider, "requires_public_media", False)

    async def run(self, state: PipelineRunState, plans: List[SegmentPlan], *,
                  stitch: bool = True, aspect: str = "9:16", fps: int = 30) -> PipelineRunState:
        ordered = sorted(plans, key=lambda p: p.segment_id)
        state.blockers = []
        state.last_error = None
        state.final_path = None
        state.current_stage = "VIDEO_GENERATION"
        try:
            if state.workdir and Path(state.workdir).resolve() != self.workdir:
                raise BlockerError("output directory differs from saved run")
            state.workdir = str(self.workdir)
            if not ordered or len({p.segment_id for p in ordered}) != len(ordered):
                raise BlockerError("empty plan or duplicate segment ids")
            serialized = [p.model_dump() for p in ordered]
            if state.plans and state.plans != serialized:
                raise BlockerError("plan differs from checkpoint; start a separate run")
            planned_duration = ordered[-1].time_end
            budget_limit = (state.planned_total_duration_seconds
                            if state.planned_total_duration_seconds is not None
                            else state.budget.max_total_duration_seconds)
            if planned_duration > budget_limit:
                raise BlockerError("planned duration exceeds run budget")
            if stitch and (not shutil.which("ffmpeg") or not shutil.which("ffprobe")):
                raise BlockerError("ffmpeg and ffprobe are required before generation")
            for p in ordered:
                if p.provider != state.provider or p.model != state.model:
                    raise BlockerError("plan provider/model differs from run")
                if p.provider != self.provider.name:
                    raise BlockerError("provider instance differs from saved plan")
            state.plans = serialized
            for plan in ordered:
                self._ensure(plan, state)
            self._save(state)
            if stitch and any(s.native_audio for s in state.segments.values()):
                raise BlockerError("final renderer does not preserve native audio; generate clips "
                                   "without stitching or use a separate approved voiceover track")
            # Reject unsupported live chaining before spending on the first clip.
            needs_chain = any(p.start_frame_source == "previous_last_frame" and
                              not state.segment(p.segment_id).remote_job_id and
                              not state.segment(p.segment_id).is_complete for p in ordered)
            if self._remote and needs_chain and self.frame_publisher is None:
                raise BlockerError("live frame chaining needs a public-URL frame publisher; "
                                   "use independent shots or configure one before submission")
            for plan in ordered:
                seg = state.segment(plan.segment_id)
                if self._remote and not seg.remote_job_id and not seg.is_complete:
                    self._validate_media(seg)
                    validate = getattr(self.provider, "validate_request", None)
                    if validate:
                        validate(self._build_request(seg))

            for index, plan in enumerate(ordered):
                seg = state.segment(plan.segment_id)
                if seg.is_complete:
                    continue
                try:
                    if (plan.start_frame_source == "previous_last_frame" and
                            not seg.remote_job_id and seg.status not in ("submitting", "submission_unknown")):
                        previous = state.segment(plan.previous_segment_id) if index else None
                        if not previous or not previous.is_complete:
                            raise BlockerError("previous segment is unavailable for frame chaining")
                        frame = self._tail_frame(previous)
                        if not frame:
                            message = f"segment {previous.segment_id}: tail frame extraction failed"
                            state.seam_failures.append(message)
                            raise BlockerError(message)
                        if self._remote:
                            frame = await self.frame_publisher(frame)
                            if not public_media_url(frame):
                                raise BlockerError("frame publisher did not return an HTTP(S) URL")
                        seg.start_frame_url = seg.image_url = frame
                        self._save(state)
                    await self._run_segment(seg, state)
                except SegmentError as exc:
                    seg.status = "failed"
                    seg.error = state.last_error = str(exc)
                    state.current_stage = "FAILED"
                    break
                except RecoverableError as exc:
                    seg.error = state.last_error = str(exc)
                    state.current_stage = "INCOMPLETE"
                    break
                self._save(state)

            complete = [state.segment(p.segment_id) for p in ordered]
            if not all(s.is_complete for s in complete):
                if state.current_stage == "VIDEO_GENERATION":
                    state.current_stage = "INCOMPLETE"
                return state
            if not stitch:
                state.current_stage = "GENERATED"
                return state
            state.current_stage = "STITCHING"
            self._save(state)
            try:
                await self._stitch(complete, aspect, fps)
                state.final_path = str(self.workdir / "final.mp4")
                state.current_stage = "STITCHED"
            except (MediaCommandError, MediaToolMissing, OSError, ValueError, RuntimeError) as exc:
                state.current_stage = "FAILED"
                state.last_error = f"stitch failed: {exc}"
        except (BlockerError, AuthError, ValidationError, ValueError) as exc:
            state.blockers.append(str(exc))
            state.last_error = str(exc)
            state.current_stage = "BLOCKED"
        finally:
            self._save(state)
        return state

    def _validate_media(self, seg):
        media = [seg.image_url, seg.start_frame_url, seg.end_frame_url, seg.audio_url,
                 *seg.reference_images, *seg.reference_videos]
        if any(value and not public_media_url(value) for value in media):
            raise BlockerError("remote providers require HTTP(S) media URLs, not local files")

    async def _run_segment(self, seg, state):
        # Always keep/query a known handle, including legacy 'failed' checkpoints.
        if seg.remote_job_id:
            status = await self._query(seg, state)
        elif seg.status in ("submitting", "submission_unknown"):
            raise BlockerError("submission outcome unknown; reconcile with provider before retrying")
        elif seg.status in ("succeeded", "downloading") and seg.output_url:
            status = VideoTaskStatus(remote_job_id="recovery", state=VideoTaskState.SUCCEEDED,
                                     video_url=seg.output_url)
        elif seg.status == "failed":
            raise SegmentError("failed segment requires an explicit new run to generate again")
        else:
            req = self._build_request(seg)
            task = await self._submit(req, seg, state)
            if not task.remote_job_id:
                seg.status = "submission_unknown"
                raise BlockerError("provider returned no remote job id; do not auto-resubmit")
            seg.remote_job_id = task.remote_job_id
            seg.status = "submitted"
            self._save(state)  # durable before first poll, download, or next segment
            status = VideoTaskStatus(remote_job_id=seg.remote_job_id, state=VideoTaskState.QUEUED)

        deadline = time.monotonic() + self.poll_timeout
        while not status.terminal:
            if time.monotonic() >= deadline:
                seg.status = "generating"
                raise RecoverableError("poll timed out; remote job preserved for resume")
            await asyncio.sleep(self.poll_interval)
            status = await self._query(seg, state)
            seg.status = "generating"
            self._save(state)
        if status.state in (VideoTaskState.FAILED, VideoTaskState.EXPIRED):
            raise SegmentError(f"task {status.state.value}: {status.error_message or 'no detail'}")
        if not status.video_url:
            raise RecoverableError("successful task has no video URL; remote job preserved")
        seg.output_url, seg.last_frame_url = status.video_url, status.last_frame_url
        seg.status = "downloading"
        self._save(state)
        local = self.workdir / f"segment_{seg.segment_id:03d}.mp4"
        # Providers write to a staging filename; partial downloads never count as complete.
        partial = local.with_suffix(".download.mp4")
        try:
            await self.provider.download_result(status, partial)
            if not partial.is_file() or not partial.stat().st_size:
                raise IOError("empty or missing download")
            partial.replace(local)
        except (OSError, httpx.HTTPError, ProviderError) as exc:
            raise RecoverableError(f"download failed; resume existing job: {type(exc).__name__}") from exc
        seg.local_path = str(local)
        seg.status, seg.error = "succeeded", None
        self._save(state)

    async def _submit(self, req, seg, state):
        max_retries = state.budget.max_retries_per_segment
        for attempt in range(seg.retry_count, max_retries + 1):
            seg.retry_count = attempt
            seg.status = "submitting"
            self._save(state)  # crash here must block blind replay even without a handle
            try:
                return await self.provider.create_task(req)
            except (AuthError, ValidationError) as exc:
                seg.status = "pending"  # explicit rejection, no task created
                raise BlockerError(f"submission rejected: {exc}") from exc
            except RateLimitError:
                seg.status = "pending"
                self._save(state)
                if attempt < max_retries:
                    await asyncio.sleep(self.poll_interval * (2 ** attempt))
            except (ProviderError, httpx.HTTPError, ValueError) as exc:
                seg.status = "submission_unknown"
                self._save(state)
                raise BlockerError("submission outcome unknown; reconcile with provider; "
                                   f"automatic retry disabled ({type(exc).__name__})") from exc
        raise SegmentError(f"submit rate limit exhausted after {max_retries} retries")

    async def _query(self, seg, state):
        for attempt in range(state.budget.max_retries_per_segment + 1):
            try:
                return await self.provider.get_task(seg.remote_job_id)
            except (AuthError, ValidationError) as exc:
                raise BlockerError(f"query rejected: {exc}") from exc
            except (RateLimitError, ProviderFailure, TimeoutError, httpx.HTTPError) as exc:
                if attempt == state.budget.max_retries_per_segment:
                    raise RecoverableError(f"query unavailable ({type(exc).__name__}); resume later") from exc
                await asyncio.sleep(self.poll_interval * (2 ** attempt))
            except ProviderError as exc:
                raise RecoverableError(f"query failed ({type(exc).__name__}); remote job preserved") from exc

    def _ensure(self, plan, state):
        seg = state.ensure_segment(plan.segment_id)
        if seg.provider and (seg.provider != plan.provider or seg.model != plan.model):
            raise BlockerError("saved segment provider/model mismatch")
        for field in ("time_start", "time_end", "duration_seconds", "generation_duration_seconds",
                      "provider", "model", "start_frame_source", "end_frame_source",
                      "previous_segment_id", "audio_source"):
            setattr(seg, field, getattr(plan, field))
        if not seg.prompt:
            seg.prompt = state.objective
        if not seg.idempotency_key:
            seg.idempotency_key = f"{state.run_id}:{seg.provider}:{seg.segment_id}"
        return seg

    def _build_request(self, seg):
        return VideoGenerationRequest(
            provider=seg.provider, model=seg.model, prompt=seg.prompt,
            negative_prompt=seg.negative_prompt, image_url=seg.start_frame_url or seg.image_url,
            end_frame_url=seg.end_frame_url, reference_images=seg.reference_images,
            reference_videos=seg.reference_videos, audio_url=seg.audio_url,
            duration_seconds=seg.generation_duration_seconds or math.ceil(seg.duration_seconds),
            aspect_ratio=seg.aspect_ratio, resolution=seg.resolution,
            native_audio=seg.native_audio, idempotency_key=seg.idempotency_key,
            metadata={"segment_id": seg.segment_id})

    def _tail_frame(self, seg):
        return extract_last_frame_safe(seg.local_path, str(self.workdir / f"last_frame_{seg.segment_id}.png"))

    async def _stitch(self, segments, aspect, fps):
        overlaps = [max(0.0, previous.time_end - current.time_start)
                    for previous, current in zip(segments, segments[1:])]
        overlap = overlaps[0] if overlaps else 0.0
        if any(abs(value - overlap) > 1e-6 for value in overlaps[1:]):
            raise ValueError("stitching requires a uniform overlap between adjacent segments")
        partial = self.workdir / "final.rendering.mp4"
        partial.unlink(missing_ok=True)
        await stitch_segments([s.local_path for s in segments], [s.duration_seconds for s in segments],
                              overlap_seconds=overlap, output_path=str(partial), aspect=aspect,
                              fps=fps, workdir=str(self.workdir / "stitch"))
        info = probe_video(str(partial))
        expected = segments[-1].time_end
        if (not info or not info.get("width") or not info.get("height") or
                abs(info.get("duration", 0) - expected) > max(0.15, 2 / fps)):
            raise ValueError("final video missing, unreadable, or duration differs from complete plan")
        partial.replace(self.workdir / "final.mp4")

    def _sync_lists(self, state):
        state.completed = sorted(v.segment_id for v in state.segments.values() if v.is_complete)
        state.failed = sorted(v.segment_id for v in state.segments.values() if v.status == "failed")
        state.pending = sorted(v.segment_id for v in state.segments.values()
                               if not v.is_complete and v.status != "failed")


__all__ = ["VideoPipelineRunner", "SegmentError", "BlockerError"]
