"""FFmpeg/ffprobe media utilities. Renderer & technical QA both sit on this.

Status: `implemented` (subprocess wrappers). `planned` parts marked inline.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional


class MediaToolMissing(RuntimeError):
    """Raised when ffmpeg / ffprobe is not installed."""


class MediaCommandError(RuntimeError):
    """Raised when an ffmpeg/ffprobe invocation fails."""


def _which(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise MediaToolMissing(
            f"'{tool}' not found on PATH. Install ffmpeg to use media utilities."
        )
    return path


def probe_video(path: str) -> Dict:
    """Return duration/fps/resolution/audio-face via ffprobe.

    Raises MediaToolMissing or MediaCommandError. Unknown fields are omitted
    rather than guessed.
    """
    ffprobe = _which("ffprobe")
    cmd = [
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaCommandError(proc.stderr.strip() or "ffprobe failed")
    data = json.loads(proc.stdout or "{}")
    info: Dict = {}
    streams = data.get("streams", [])
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    astream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if vstream:
        info["width"] = vstream.get("width")
        info["height"] = vstream.get("height")
        info["fps"] = _parse_fps(vstream.get("r_frame_rate"))
    info["duration"] = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    info["has_audio"] = astream is not None
    return info


def _parse_fps(r_frame_rate: Optional[str]) -> Optional[float]:
    if not r_frame_rate or "/" not in r_frame_rate:
        return None
    try:
        num, den = r_frame_rate.split("/")
        den = float(den)
        return round(float(num) / den, 3) if den else None
    except (ValueError, ZeroDivisionError):
        return None


def extract_last_frame(video: str, out_path: str, pad: float = 0.0) -> str:
    """Extract a JPEG of the final frame via ffmpeg. Returns out_path."""
    ffmpeg = _which("ffmpeg")
    info = probe_video(video)
    dur = info.get("duration", 0.0)
    at = max(0.0, dur - max(0.0, pad))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", video,
        "-frames:v", "1", "-q:v", "2", out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaCommandError(proc.stderr.strip() or "ffmpeg frame extract failed")
    return out_path
