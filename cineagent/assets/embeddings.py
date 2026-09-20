"""Embedding providers. Deterministic offline fallback marked experimental;
real semantic embeddings plug in here later."""
from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import List, Sequence

_TOKEN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, text: str) -> List[float]:
        raise NotImplementedError

    @abstractmethod
    def similarity(self, a: Sequence[float], b: Sequence[float]) -> float:
        raise NotImplementedError

    @property
    def dim(self) -> int:
        raise NotImplementedError


class TokenHashEmbedder(EmbeddingProvider):
    """Deterministic feature-hashing embedder. Status: `experimental`.

    Good enough for offline dedup/tag similarity and tests; swap for a real
    model (e.g. sentence-transformers) behind the same interface when needed.
    """

    DIM = 128

    def __init__(self, dim: int = 128) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self._dim
        tokens = _TOKEN.findall((text or "").lower())
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
            idx = h % self._dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def similarity(self, a: Sequence[float], b: Sequence[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (na * nb)
