"""AssetLibrary — semantic, dedup, reuse-first store over AssetRepo."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..domain.asset import Asset
from ..storage.repositories import AssetRepo
from .embeddings import EmbeddingProvider


class AssetLibrary:
    def __init__(self, repo: AssetRepo, embedder: EmbeddingProvider) -> None:
        self.repo = repo
        self.embedder = embedder

    def add(self, asset: Asset) -> Asset:
        """Hash-dedup: if a file with the same content hash exists, reuse it.

        Returns the canonical stored asset (existing on duplicate).
        """
        if asset.hash:
            existing = self.repo.find_by_hash(asset.hash)
            if existing is not None:
                self.repo.increment_reuse(existing.asset_id)
                return existing
        asset.meta["embedding"] = self.embedder.embed(asset.semantic_text())
        self.repo.upsert(asset)
        return asset

    def search(
        self, text: str, threshold: float, project_id: str = "", limit: int = 5,
    ) -> List[Tuple[Asset, float]]:
        """Return assets whose semantic similarity to `text` >= threshold."""
        q = self.embedder.embed(text)
        hits: List[Tuple[Asset, float]] = []
        for asset in self.repo.assets_for(project_id) + self.repo.assets_for(""):
            if not asset.meta.get("embedding"):
                continue
            sim = self.embedder.similarity(q, asset.meta["embedding"])
            if sim >= threshold:
                hits.append((asset, round(sim, 4)))
        hits.sort(key=lambda t: t[1], reverse=True)
        return hits[:limit]

    def best(self, text: str, threshold: float, project_id: str = "") -> Optional[Asset]:
        hits = self.search(text, threshold, project_id=project_id, limit=1)
        return hits[0][0] if hits else None
