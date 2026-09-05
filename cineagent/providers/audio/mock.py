"""Deterministic AudioProvider for offline runs & tests (native timestamps)."""
from __future__ import annotations

from ...domain.timeline import Word
from .base import AudioProvider, TTSRequest, TTSResult


class MockAudioProvider(AudioProvider):
    """Synthesizes an inert duration and per-char word timestamps (no audio file).

    Status: `implemented` for testing; real TTS adapters (ElevenLabs/OpenAI/local)
    are separate and marked `planned`.
    """

    name = "mock"
    CHARS_PER_SEC = 4.0  # ~4 chars/second for zh narration
    MIN_DURATION = 0.5

    @property
    def provides_native_timestamps(self) -> bool:
        return True

    async def synthesize(self, req: TTSRequest) -> TTSResult:
        text = req.text or ""
        chars = [c for c in text if c.strip()]
        duration = max(self.MIN_DURATION, len(chars) / self.CHARS_PER_SEC)
        words: list[Word] = []
        per = duration / max(1, len(chars))
        t = 0.0
        for c in chars:
            words.append(Word(text=c, start=round(t, 4), end=round(t + per, 4)))
            t += per
        if not words and text:
            words = [Word(text=text, start=0.0, end=duration)]
        return TTSResult(
            audio_uri=f"mock://{req.voice}/{hash(text)}.wav",
            duration=round(duration, 3),
            words=words,
            native=True,
        )
