"""CineAgent v4 video-pipeline CLI.

The Seedance/Kling animation entry point (the v4 replacement for the legacy
run_pipeline.py, which is retained only as migration history). Fully offline
path via ``--video-provider mock``; real providers need env keys.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from .domain import PipelineRunState
from .orchestration import VideoPipelineRunner, plan_segments
from .providers.capability import default_registry

DEFAULT_MODELS = {
    "kling": "kling-v3",
    "seedance": "doubao-seedance-2-5-260628",
    "mock": "mock-video",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cineagent-video",
        description="Seedance/Kling animation pipeline (5-15s segments, long-video segmentation).",
    )
    p.add_argument("--topic", required=True, help="animation objective / prompt")
    p.add_argument("--video-provider", choices=["kling", "seedance", "mock"], default="kling")
    p.add_argument("--model", default=None, help="override provider model id")
    p.add_argument("--scenes", type=int, default=1, help="scene count hint (for per-scene prompts)")
    p.add_argument("--duration", type=int, default=5, help="per-segment duration (s)")
    p.add_argument("--total-duration", type=float, default=None, help="target film length (s)")
    p.add_argument("--long-video", action="store_true", help="force segmentation")
    p.add_argument("--plan-only", action="store_true", help="print the segment plan and exit")
    p.add_argument("--segment-max-duration", type=float, default=None,
                   help="max seconds per segment (default: model max)")
    p.add_argument("--native-audio", action="store_true")
    p.add_argument("--multi-shot", action="store_true",
                   help="UNVERIFIED for Seedance/Kling; accepted but not forwarded")
    p.add_argument("--resume", default=None, help="resume from a state JSON")
    p.add_argument("--state-file", default=None, help="where to write the run state")
    p.add_argument("--output-dir", default="/tmp/cineagent-run")
    p.add_argument("--aspect", default="9:16")
    p.add_argument("--resolution", default="720p")
    return p


def _make_provider(name: str):
    if name == "mock":
        from .providers.video.mock_generation import MockGenerationProvider
        return MockGenerationProvider(out_dir="/tmp/cineagent-run/mock", auto_succeed=True)
    if name == "seedance":
        if not os.environ.get("ARK_API_KEY"):
            raise SystemExit("error: --video-provider seedance requires ARK_API_KEY")
        from .providers.video.seedance import SeedanceVideoProvider
        return SeedanceVideoProvider()
    if name == "kling":
        if not (os.environ.get("KLING_ACCESS_KEY") and os.environ.get("KLING_SECRET_KEY")):
            raise SystemExit("error: --video-provider kling requires "
                             "KLING_ACCESS_KEY and KLING_SECRET_KEY")
        from .providers.video.kling import KlingVideoProvider
        return KlingVideoProvider()
    raise SystemExit(f"error: unknown provider {name}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.multi_shot:
        print("warning: --multi-shot is UNVERIFIED for Seedance/Kling and is not "
              "forwarded to the API", file=sys.stderr)

    model = args.model or DEFAULT_MODELS.get(args.video_provider, "")
    cap = default_registry().get(args.video_provider, model)
    max_dur = args.segment_max_duration or (cap.max_duration if cap else args.duration)

    total = args.total_duration or (args.duration * args.scenes)
    if args.long_video or total > max_dur:
        plans = plan_segments(total, max_dur, overlap_seconds=0.2,
                              provider=args.video_provider, model=model)
    else:
        plans = plan_segments(total, max(total, 1e-6), overlap_seconds=0.0,
                              provider=args.video_provider, model=model)

    if args.plan_only:
        print(json.dumps([p.model_dump() for p in plans], ensure_ascii=False, indent=2))
        return 0

    if args.resume and Path(args.resume).exists():
        state = PipelineRunState.from_file(args.resume)
    else:
        state = PipelineRunState(
            run_id=f"run-{uuid.uuid4().hex[:12]}",
            objective=args.topic,
            locked_decisions=[
                "Agnes 全面棄用",
                "動畫只使用 Seedance 與 Kling",
            ],
            provider=args.video_provider,
            model=model,
        )

    for plan in plans:
        seg = state.ensure_segment(plan.segment_id)
        seg.duration_seconds = plan.duration_seconds
        seg.provider = plan.provider
        seg.model = plan.model
        seg.prompt = args.topic
        seg.aspect_ratio = args.aspect
        seg.resolution = args.resolution
        seg.native_audio = args.native_audio

    provider = _make_provider(args.video_provider)
    runner = VideoPipelineRunner(provider, args.output_dir)
    state = asyncio.run(runner.run(state, plans, aspect=args.aspect))

    state_file = args.state_file or str(Path(args.output_dir) / "state.json")
    state.to_file(state_file)
    print(f"state: {state_file}")
    print(f"stage: {state.current_stage}")
    print(f"completed: {state.completed}")
    print(f"failed: {state.failed}")
    if state.blockers:
        print(f"blockers: {state.blockers}")
    if state.last_error:
        print(f"last_error: {state.last_error}")
    final = Path(args.output_dir) / "final.mp4"
    if final.exists():
        print(f"final: {final}")
    return 0 if (not state.failed and not state.blockers) else 1


if __name__ == "__main__":
    raise SystemExit(main())
