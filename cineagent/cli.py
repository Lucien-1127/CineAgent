"""Video CLI. Saved plans/inputs are authoritative when resuming a paid run."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import uuid

from .domain import Budget, PipelineRunState
from .orchestration import VideoPipelineRunner, plan_segments
from .orchestration.planner import SegmentPlan
from .providers.capability import default_registry
from .storage.run_lock import run_lock

DEFAULT_MODELS = {"kling": "kling-v3", "seedance": "doubao-seedance-2-5-260628",
                  "mock": "mock-video", "orcarouter": "kling/kling-v3"}


def build_parser():
    p = argparse.ArgumentParser(prog="cineagent-video")
    p.add_argument("--topic", help="required for a new run; omit when resuming")
    p.add_argument("--video-provider", choices=list(DEFAULT_MODELS))
    p.add_argument("--model")
    p.add_argument("--scenes", type=int)
    p.add_argument("--duration", type=int)
    p.add_argument("--total-duration", type=float)
    p.add_argument("--long-video", action="store_true")
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--segment-max-duration", type=float)
    p.add_argument("--native-audio", action="store_true", default=None)
    p.add_argument("--multi-shot", action="store_true")
    p.add_argument("--independent-shots", action="store_true",
                   help="separate clips without last-frame chaining (no upload required)")
    p.add_argument("--image-url", help="public first-frame URL")
    p.add_argument("--resume", help="existing checkpoint, restored without regeneration")
    p.add_argument("--state-file")
    p.add_argument("--output-dir")
    p.add_argument("--aspect")
    p.add_argument("--resolution")
    return p


def _make_provider(name):
    if name == "orcarouter":
        if not os.environ.get("ORCAROUTER_API_KEY"):
            raise ValueError("ORCAROUTER_API_KEY is required")
        from .providers.video.orcarouter import OrcaRouterVideoProvider
        return OrcaRouterVideoProvider()
    if name == "mock":
        from .providers.video.mock_generation import MockGenerationProvider
        return MockGenerationProvider(out_dir=f"/tmp/cineagent-run/mock-{uuid.uuid4().hex[:12]}",
                                      auto_succeed=True)
    if name == "seedance":
        if not os.environ.get("ARK_API_KEY"):
            raise ValueError("ARK_API_KEY is required")
        from .providers.video.seedance import SeedanceVideoProvider
        return SeedanceVideoProvider()
    if name == "kling":
        if not (os.environ.get("KLING_ACCESS_KEY") and os.environ.get("KLING_SECRET_KEY")):
            raise ValueError("KLING_ACCESS_KEY and KLING_SECRET_KEY are required")
        from .providers.video.kling import KlingVideoProvider
        return KlingVideoProvider()
    raise ValueError("unknown provider")


def _new_run(args):
    if not args.topic:
        raise ValueError("--topic is required for a new run")
    provider = args.video_provider or "orcarouter"
    model = args.model or DEFAULT_MODELS[provider]
    if provider == "orcarouter":
        from .providers.video.orcarouter import duration_policy
        minimum, maximum, allowed = duration_policy(model)
    else:
        cap = default_registry().get(provider, model)
        if not cap or cap.status == "planned":
            raise ValueError("unknown or unimplemented provider/model")
        maximum, minimum, allowed = cap.max_duration, 1, None
        if provider == "kling":
            minimum, allowed = 5, [5, 10]
        elif provider == "seedance":
            from .providers.video.seedance import MODEL_CAPS
            minimum = MODEL_CAPS[model]["duration"][0]
    max_dur = args.segment_max_duration if args.segment_max_duration is not None else maximum
    if max_dur > maximum or max_dur < minimum:
        raise ValueError("segment maximum outside model duration limits")
    duration = args.duration if args.duration is not None else 5
    scenes = args.scenes if args.scenes is not None else 1
    if duration <= 0 or scenes <= 0:
        raise ValueError("duration and scenes must be positive")
    total = args.total_duration if args.total_duration is not None else duration * scenes
    if total > 60:
        raise ValueError("this CLI run budget is at most 60 seconds")
    overlap = 0.0 if args.independent_shots or total <= max_dur else 0.2
    plans = plan_segments(total, max_dur, overlap, provider, model,
                          min_segment_duration=minimum, allowed_durations=allowed)
    if args.independent_shots:
        for plan in plans:
            plan.start_frame_source, plan.previous_segment_id = "keyframe", None
    state = PipelineRunState(run_id="run-" + uuid.uuid4().hex[:12], objective=args.topic,
        provider=provider, model=model,
        budget=Budget(max_total_duration_seconds=total),
        locked_decisions=["Agnes 全面棄用", "動畫只使用 Seedance 與 Kling"],
        plans=[plan.model_dump() for plan in plans],
        planned_total_duration_seconds=total)
    for plan in plans:
        seg = state.ensure_segment(plan.segment_id)
        seg.prompt = args.topic
        seg.provider, seg.model = provider, model
        seg.aspect_ratio, seg.resolution = args.aspect or "9:16", args.resolution or "720p"
        seg.native_audio = bool(args.native_audio)
        seg.image_url = args.image_url
    return state, plans


def _resume_run(args):
    if not Path(args.resume).is_file():
        raise ValueError("resume file does not exist; refusing to start a new paid run")
    state = PipelineRunState.from_file(args.resume)
    if not state.plans:
        raise ValueError("legacy checkpoint has no durable plan; reconcile/migrate before resume")
    for field, current in (("video_provider", state.provider), ("model", state.model),
                           ("topic", state.objective)):
        supplied = getattr(args, field)
        if supplied is not None and supplied != current:
            raise ValueError(f"--{field.replace('_', '-')} conflicts with saved run")
    if any(getattr(args, f) is not None for f in ("duration", "scenes", "total_duration",
            "segment_max_duration", "aspect", "resolution", "native_audio", "image_url")) or args.independent_shots or args.long_video:
        raise ValueError("resume restores saved inputs; generation overrides are not allowed")
    plans = [SegmentPlan.model_validate(p) for p in state.plans]
    if set(state.segments) != {str(p.segment_id) for p in plans}:
        raise ValueError("checkpoint segments do not match saved plans")
    return state, plans


def _run_aspect(state, plans):
    aspects = {state.segment(plan.segment_id).aspect_ratio for plan in plans}
    if len(aspects) != 1:
        raise ValueError("all segments in a run must share the same aspect ratio")
    return aspects.pop()


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.multi_shot:
            raise ValueError("multi-shot authoring is not implemented")
        resume_path = Path(args.resume).resolve() if args.resume else None
        # Lock the checkpoint before reading it, then lock the resolved output directory
        # before starting or resuming a job.
        output = Path(args.output_dir or (str(resume_path.parent) if resume_path
                      else "/tmp/cineagent-run/" + uuid.uuid4().hex[:12])).resolve()
        state_path = Path(args.state_file or args.resume or output / "state.json").resolve()
        if args.resume and state_path != resume_path:
            raise ValueError("resume must update the original checkpoint")
        with ExitStack() as stack:
            if not args.plan_only:
                stack.enter_context(run_lock(str(state_path) + ".lock"))
            state, plans = _resume_run(args) if args.resume else _new_run(args)
            if args.resume and not args.output_dir and state.workdir:
                output = Path(state.workdir).resolve()
            if not args.plan_only:
                stack.enter_context(run_lock(str(output / ".run.lock")))
            if args.plan_only:
                print(json.dumps([p.model_dump() for p in plans], ensure_ascii=False, indent=2))
                return 0
            if not args.resume and (state_path.exists() or (output / "final.mp4").exists()):
                raise ValueError("existing run found; use --resume or a new output directory")
            aspect = _run_aspect(state, plans)
            provider = _make_provider(state.provider)
            runner = VideoPipelineRunner(provider, str(output), state_file=str(state_path))
            state = asyncio.run(runner.run(state, plans, aspect=aspect))
            print(f"state: {state_path}\nstage: {state.current_stage}\ncompleted: {state.completed}")
            if state.last_error:
                print(f"last_error: {state.last_error}", file=sys.stderr)
            if state.current_stage == "STITCHED" and state.final_path and Path(state.final_path).is_file():
                print(f"final: {state.final_path}")
                return 0
            return 1
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
