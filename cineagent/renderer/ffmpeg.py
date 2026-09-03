"""FFmpeg renderer — utility/fallback that actually produces a playable MP4.

Pipeline: normalize each segment -> concat video -> (optional) burn captions ->
(optional) mix audio -> final MP4. FFmpeg is the bottom media utility; Remotion
is the primary scripting renderer (planned), this is the always-available base.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..media.ffmpeg import _which
from .base import RenderComposition, RenderSegment, RendererProvider


class FFmpegRenderer(RendererProvider):
    name = "ffmpeg"
    status = "implemented"

    def __init__(self, workdir: str = "/tmp/cineagent-render") -> None:
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)

    async def render(self, comp: RenderComposition) -> str:
        if not comp.segments:
            raise ValueError("empty render composition (no segments)")
        ffmpeg = _which("ffmpeg")

        # 1) Normalize each segment into an h264 mp4 of its exact duration.
        normalized: list[str] = []
        for i, seg in enumerate(comp.segments):
            out = str(self.workdir / f"seg_{i}.mp4")
            self._normalize_segment(ffmpeg, seg, out, comp.aspect, comp.fps)
            normalized.append(out)

        # 2) Concat (same codecs/params) into the final video track.
        listf = self.workdir / "concat.txt"
        listf.write_text("\n".join(f"file '{p}'" for p in normalized) + "\n")
        final_video = str(self.workdir / "video_only.mp4")
        self._run([
            ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0",
            "-i", str(listf), "-c", "copy", final_video,
        ])

        # 3) Burn captions if provided.
        if comp.captions_srt:
            burned = str(self.workdir / "burned.mp4")
            self._run([
                ffmpeg, "-y", "-v", "error", "-i", final_video,
                "-vf", f"subtitles='{comp.captions_srt}'",
                "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
                "-c:a", "copy", burned,
            ])
            final_video = burned

        # 4) Add audio (or silent track) and write the final file.
        args = [ffmpeg, "-y", "-v", "error", "-i", final_video]
        if comp.audio:
            args += ["-i", comp.audio, "-map", "0:v", "-map", "1:a",
                     "-c:v", "copy", "-c:a", "aac", "-shortest"]
        else:
            args += [ "-c:v", "copy", "-f", "lavfi",
                     "-i", "anullsrc=r=44100:cl=stereo",
                     "-c:a", "aac", "-shortest"]
            # move lavfi input into the -i list properly
            args = [ffmpeg, "-y", "-v", "error", "-i", final_video,
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-shortest"]
        self._run(args + [comp.output_path])
        return comp.output_path

    def _normalize_segment(
        self, ffmpeg: str, seg: RenderSegment, out: str,
        aspect: str, fps: int,
    ) -> None:
        dur = max(0.2, seg.duration)
        if seg.kind == "image":
            self._run([
                ffmpeg, "-y", "-v", "error", "-loop", "1", "-i", seg.path,
                "-t", f"{dur:.3f}", "-r", str(fps), "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", out,
            ])
        else:
            # video: trim to [seg.start, seg.start+dur]
            self._run([
                ffmpeg, "-y", "-v", "error", "-ss", f"{seg.start:.3f}",
                "-i", seg.path, "-t", f"{dur:.3f}", "-r", str(fps),
                "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "20",
                "-preset", "veryfast", out,
            ])

    @staticmethod
    def _run(cmd) -> None:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise _RenderError(proc.stderr.strip() or "ffmpeg render failed")


class _RenderError(RuntimeError):
    pass


def make_test_media(workdir: str, image="image.png", wav="tone.wav"):
    """Create a tiny test PNG + tone WAV so render smoke tests have real inputs."""
    from ..media.ffmpeg import _which
    ffmpeg = _which("ffmpeg")
    d = Path(workdir)
    d.mkdir(parents=True, exist_ok=True)
    img = str(d / image)
    w = str(d / wav)
    subprocess.run([
        ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=navy:s=540x960:d=1", "-frames:v", "1", img,
    ], check=True)
    subprocess.run([
        ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=2", w,
    ], check=True)
    return img, w
