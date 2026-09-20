"""Caption generation from canonical timing data (never re-guessed)."""
from __future__ import annotations

from typing import List, Tuple

from ..domain.timeline import CaptionCue, Word


def group_caption_words(words: List[Word], max_chars: int = 8) -> List[CaptionCue]:
    """Group word-level timings into short sub-captions (max ~max_chars chars).

    Chinese narration: words are individual characters; we group consecutive
    characters into a caption, keeping the earliest start and latest end.
    """
    cues: List[CaptionCue] = []
    cur: List[Word] = []
    for w in words:
        if cur and len("".join(x.text for x in cur)) + len(w.text) > max_chars:
            cues.append(CaptionCue(
                text="".join(x.text for x in cur),
                start=cur[0].start,
                end=cur[-1].end,
            ))
            cur = []
        cur.append(w)
    if cur:
        cues.append(CaptionCue(
            text="".join(x.text for x in cur),
            start=cur[0].start,
            end=cur[-1].end,
        ))
    return cues


def build_srt(cues: List[CaptionCue]) -> str:
    """Render caption cues as SubRip (SRT) text."""
    lines: List[str] = []
    for i, cue in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(f"{_ts(cue.start)} --> {_ts(cue.end)}")
        lines.append(cue.text)
        lines.append("")
    return "\n".join(lines)


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
