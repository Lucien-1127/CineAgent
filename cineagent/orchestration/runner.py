"""Resume-safe video pipeline runner.

Plan -> generate (submit/poll/download) -> frame-link -> stitch. Each segment
is independently recoverable: completed segments are never re-generated, a
segment with a remote job id is first queried (never blindly re-submitted),
and retryable errors respect the per-run budget.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import List, Optional

from ..domain.pipeline import PipelineRunState, SegmentState
from ..providers.base import (
    AuthError,
    ProviderFailure,
    RateLimitError,
    TimeoutError,
    ValidationError,
)
from ..providers.video.generation import GenerationProvider
from ..providers.video.schemas import (
    VideoGenerationRequest,
    VideoTaskState,
    VideoTaskStatus,
)
from .planner import SegmentPlan
from .stitching import extract_last_frame_safe, stitch_segments


class SegmentError(Exception):
    """A single segment failed and may be retried."""


class BlockerError(Exception):
    """Auth/validation/payment failure: stop the whole run, do not retry."""


class VideoPipelineRunner:
    """Drives a GenerationProvider across a list of SegmentPlans."""

    def __init__(
        self,
        provider: GenerationProvider,
        workdir: str,
        poll_interval: float = 1.0,
        poll_timeout: float = 120.0,
    ) -> None:
        self.provider = provider
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    async def run(
        self,
        state: PipelineRunState,
        plans: List[SegmentPlan],
        *,
        stitch: bool = True,
        aspect: str = "9:16",
        fps: int = 30,
    ) -> PipelineRunState:
        state.current_stage = "VIDEO_GENERATION"
        ordered = sorted(plans, key=lambda p: p.segment_id)
        prev_last_frame: Optional[str] = None

        for plan in ordered:
            seg = self._ensure(plan, state)
            if seg.is_complete:
prev_last_frame = self._tail_frame(seg)
                continue

            # continuity: use the previous segment's tail frame as this
            # segment's first frame (local path works offline; real providers
            # require a public URL upload — see real-API gap note).
            if plan.start_frame_source == "previous_last_frame" and prev_last_frame:
                seg.start_frame_url = prev_last_frame
                seg.image_url = prev_last_frame

            try:
                await self._run_segment(seg, state)
            except BlockerError as exc:
                state.blockers.append(str(exc))
                state.last_error = str(exc)
                state.current_stage = "BLOCKED"
                break
            except SegmentError as exc:
                seg.error = str(exc)
                seg.status = "failed"

            if seg.is_complete:
                prev_last_frame = self._tail_frame(seg)

        self._sync_lists(state)

        if state.blockers:
            return state

        succeeded = [seg for seg in self._segments(ordered, state) if seg.is_complete]
        if stitch and succeeded:
            try:
                await self._stitch(succeeded, aspect=aspect, fps=fps)
                state.current_stage = "STITCHED"
            except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
                state.last_error = f"stitch failed: {exc}"
        return state

    # ── segment lifecycle ──────────────────────────────────────────────
    async def _run_segment(self, seg: SegmentState, state: PipelineRunState) -> None:
        req = self._build_request(seg)

        # Resume: a known remote job is queried, never blindly re-submitted.
        rid = seg.remote_job_id
        if rid and seg.status in ("submitted", "generating"):
            status = await self.provider.get_task(rid)
        else:
            task = await self._submit(req, seg, state)
            seg.remote_job_id = task.remote_job_id
            seg.status = "submitted"
            status = VideoTaskStatus(
                remote_job_id=task.remote_job_id, state=VideoTaskState.QUEUED,
            )

        status = await self._poll_until_terminal(seg, status)

        if status.state == VideoTaskState.SUCCEEDED:
            if not status.video_url:
                raise SegmentError("task succeeded but returned no video_url")
            local = self.workdir / f"segment_{seg.segment_id:03d}.mp4"
            await self.provider.download_result(status, local)
            seg.local_path = str(local)
            seg.output_url = status.video_url
            seg.last_frame_url = status.last_frame_url
            seg.status = "succeeded"
        elif status.state in (VideoTaskState.FAILED, VideoTaskState.EXPIRED):
            raise SegmentError(f"task {status.state.value}: {status.error_message or 'no detail'}")
        else:
            raise SegmentError(f"unexpected terminal state {status.state.value}")

    async def _submit(self, req, seg: SegmentState, state: PipelineRunState):
        last_exc: Optional[Exception] = None
        max_retries = state.budget.max_retries_per_segment
        for attempt in range(max_retries + 1):
            seg.retry_count = attempt
            try:
                return await self.provider.create_task(req)
            except (AuthError, ValidationError) as exc:
                raise BlockerError(
                    f"segment {seg.segment_id}: {type(exc).__name__}: {exc}"
                ) from exc
            except RateLimitError as exc:
                last_exc = exc
                if attempt < max_retries:
                    await asyncio.sleep(self.poll_interval * (2 ** attempt))
            except (ProviderFailure, TimeoutError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    await asyncio.sleep(self.poll_interval)
        raise SegmentError(
            f"segment {seg.segment_id}: submit failed after {max_retries} retries: {last_exc}"
        )

    async def _poll_until_terminal(self, seg: SegmentState, status: VideoTaskStatus) -> VideoTaskStatus:
        deadline = time.monotonic() + self.poll_timeout
        while not status.terminal:
            if time.monotonic() > deadline:
                raise SegmentError(f"segment {seg.segment_id}: poll timed out")
            await asyncio.sleep(self.poll_interval)
            status = await self.provider.get_task(seg.remote_job_id)
        return status

    # ── helpers ────────────────────────────────────────────────────────
    def _ensure(self, plan: SegmentPlan, state: PipelineRunState) -> SegmentState:
        seg = state.ensure_segment(plan.segment_id)
        seg.time_start = plan.time_start
        seg.time_end = plan.time_end
        seg.duration_seconds = plan.duration_seconds
        seg.provider = plan.provider
        seg.model = plan.model
        seg.start_frame_source = plan.start_frame_source
        seg.end_frame_source = plan.end_frame_source
        seg.previous_segment_id = plan.previous_segment_id
        seg.audio_source = plan.audio_source
        if not seg.prompt:
            seg.prompt = state.objective
        return seg

    def _build_request(self, seg: SegmentState) -> VideoGenerationRequest:
        return VideoGenerationRequest(
            provider=seg.provider,
            model=seg.model,
            prompt=seg.prompt,
            negative_prompt=seg.negative_prompt,
            image_url=seg.image_url or seg.start_frame_url,
            end_frame_url=seg.end_frame_url,
            reference_images=seg.reference_images,
            reference_videos=seg.reference_videos,
            audio_url=seg.audio_url,
            duration_seconds=int(round(seg.duration_seconds)),
            aspect_ratio=seg.aspect_ratio,
            resolution=seg.resolution,
            native_audio=seg.native_audio,
            idempotency_key=seg.remote_job_id or f"{seg.provider}:{seg.segment_id}",
            metadata={"segment_id": seg.segment_id},
        )

    def _tail_frame(self, seg: SegmentState) -> Optional[str]:
        if not seg.local_path:
            return None
        out = self.workdir / f"last_frame_{seg.segment_id}.png"
        return extract_last_frame_safe(seg.local_path, str(out))

    async def _stitch(self, segments: List[SegmentState], aspect: str, fps: int) -> None:
        videos = [s.local_path for s in segments if s.local_path]
        durations = [s.duration_seconds for s in segments if s.local_path]
        # Uniform overlap from consecutive segment times (plan_segments guarantees
        # a constant overlap); trims the duplicate head of every later segment.
        overlap = 0.0
        if len(segments) >= 2:
            overlap = max(0.0, segments[0].time_end - segments[1].time_start)
        out = str(self.workdir / "final.mp4")
        await stitch_segments(
            videos, durations, overlap_seconds=overlap, output_path=out,
            aspect=aspect, fps=fps, workdir=str(self.workdir / "stitch"),
        )

    def _sync_lists(self, state: PipelineRunState) -> None:
        state.completed = sorted(
            int(k) for k, v in state.segments.items() if v.is_complete
        )
        state.failed = sorted(
            int(k) for k, v in state.segments.items()
            if v.status == "failed"
        )
        state.pending = sorted(
            int(k) for k, v in state.segments.items()
            if v.status == "pending"
        )

    def _segments(self, ordered: List[SegmentPlan], state: PipelineRunState) -> List[SegmentState]:
        out: List[SegmentState] = []
        for p in ordered:
            seg = state.segment(p.segment_id)
            if seg is not None:
                out.append(seg)
        return out


__all__ = ["VideoPipelineRunner", "SegmentError", "BlockerError"]
