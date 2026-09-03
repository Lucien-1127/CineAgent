"""In-memory ImageProvider for tests/offline (writes a stub file)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .base import ImageProvider, ImageRequest, ImageResult


class MockImageProvider(ImageProvider):
    name = "mock-image"
    model = "mock-image-model"

    def __init__(self, out_dir: str = "/tmp/cineagent-mock-images") -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._calls = 0

    async def generate(self, req: ImageRequest) -> ImageResult:
        self._calls += 1
        digest = hashlib.sha1(req.prompt.encode("utf-8")).hexdigest()[:12]
        path = self.out_dir / f"{digest}.png"
        # write a tiny PNG-ish placeholder so downstream media tools can open it
        if not path.exists():
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 24)
        return ImageResult(uri=str(path), provider=self.name,
                           model=self.model, estimated_cost_usd=0.0)
