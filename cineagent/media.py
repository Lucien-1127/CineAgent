"""ffmpeg helpers: probing, frame extraction, cut detection, concat.

Kept dependency-free (subprocess + ffmpeg/ffprobe) because the target环境 is a
phone terminal where Python wheels are expensive; ffmpeg is already present.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

ASPECTS = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (1024, 1024),
    "4:5": (864, 1080),
    "21:9": (1680, 720),
}


class MediaError(RuntimeError):
    pass


def available() -> tuple[bool, bool]:
    return shutil.which("ffmpeg") is not None, shutil.which("ffprobe") is not None


def probe(path: str | Path) -> dict:
    """Return ``{duration, width, height, fps}`` for a media file."""
    cmd = [FFPROBE, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height,r_frame_rate:format=duration",
           "-of", "json", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise MediaError(f"ffprobe failed: {out.stderr.strip()[:300]}")
    data = json.loads(out.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    rate = stream.get("r_frame_rate", "0/1")
    try:
        num, den = rate.split("/")
        fps = round(float(num) / float(den or 1), 3)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {"duration": duration, "width": stream.get("width", 0),
            "height": stream.get("height", 0), "fps": fps}


def extract_frame(src: str | Path, timestamp: float, dest: str | Path,
                  width: int | None = None) -> Path:
    """Grab one frame at ``timestamp`` seconds."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, "-y", "-ss", f"{max(0.0, timestamp):.3f}", "-i", str(src),
           "-frames:v", "1", "-q:v", "2"]
    if width:
        cmd += ["-vf", f"scale={width}:-2"]
    cmd.append(str(dest))
    run(cmd, f"extract frame @{timestamp:.2f}s")
    if not dest.exists() or dest.stat().st_size == 0:
        raise MediaError(f"frame extraction produced nothing: {dest}")
    return dest


def sample_frames(src: str | Path, times: Iterable[float], outdir: str | Path,
                  prefix: str = "f") -> list[Path]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    return [extract_frame(src, t, outdir / f"{prefix}_{i:02d}.jpg")
            for i, t in enumerate(times)]


_SCENE_RE = re.compile(r"pts_time:([0-9.]+)")


def detect_cuts(src: str | Path, threshold: float = 0.30,
                max_shots: int = 16) -> list[float]:
    """Return cut timestamps using ffmpeg's scene score.

    ``threshold`` 0.3 is a good default for edited footage; raise it for
    handheld material where the whole frame moves.
    """
    cmd = [FFMPEG, "-hide_banner", "-i", str(src), "-filter:v",
           f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    cuts = sorted({float(m) for m in _SCENE_RE.findall(out.stderr)})
    return cuts[:max_shots]


def segments(src: str | Path, threshold: float = 0.30,
             max_shots: int = 16) -> list[tuple[float, float]]:
    """Cut list → ``[(start, end), ...]`` covering the whole clip."""
    info = probe(src)
    duration = info["duration"] or 0.0
    cuts = detect_cuts(src, threshold, max_shots)
    bounds = [0.0] + [c for c in cuts if 0.05 < c < duration - 0.05] + [duration]
    spans = [(round(a, 2), round(b, 2)) for a, b in zip(bounds, bounds[1:]) if b - a > 0.15]
    return spans


def concat(videos: Iterable[str | Path], dest: str | Path,
           fade: float = 0.0, fps: int = 24) -> Path:
    """Concatenate clips; ``fade`` > 0 uses crossfades, else a hard cut list."""
    items = [Path(v) for v in videos]
    if not items:
        raise MediaError("nothing to concat")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if len(items) == 1:
        shutil.copyfile(items[0], dest)
        return dest

    if fade <= 0:
        listing = dest.with_suffix(".txt")
        listing.write_text("".join(f"file '{p.resolve()}'\n" for p in items), encoding="utf-8")
        run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", str(dest)], "concat (hard cuts)")
        return dest

    # Crossfade chain: normalise each clip to the first clip's frame size, then
    # xfade sequentially.
    first = probe(items[0])
    width = (first["width"] or 1280) // 2 * 2
    height = (first["height"] or 720) // 2 * 2
    norm = []
    for i, item in enumerate(items):
        out = dest.parent / f"_norm_{i}.mp4"
        run([FFMPEG, "-y", "-i", str(item), "-r", str(fps),
             "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
             "-an", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out)],
            f"normalise {i}")
        norm.append(out)

    acc = norm[0]
    for i, nxt in enumerate(norm[1:], start=1):
        out = dest.parent / f"_xfade_{i}.mp4"
        dur_a = probe(acc)["duration"]
        offset = max(0.0, dur_a - fade)
        run([FFMPEG, "-y", "-i", str(acc), "-i", str(nxt), "-filter_complex",
             f"[0:v][1:v]xfade=transition=fade:duration={fade}:offset={offset:.3f},"
             f"format=yuv420p[v]", "-map", "[v]", "-c:v", "libx264", "-crf", "18", str(out)],
            f"xfade {i}")
        acc = out
    shutil.copyfile(acc, dest)
    for tmp in norm + list(dest.parent.glob("_xfade_*.mp4")):
        tmp.unlink(missing_ok=True)
    return dest


def run(cmd: list[str], label: str, timeout: int = 300) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise MediaError(f"{label} failed (rc={proc.returncode}): {proc.stderr[-400:]}")
    return proc
