"""Asset — canonical, reuse-first media entity."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import AssetSource, AssetType


class Asset(BaseModel):
    """A reusable media artifact. Reuse-before-generate is enforced via this table."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    project_id: str = ""
    source: AssetSource = AssetSource.LIBRARY
    type: AssetType = AssetType.VIDEO
    uri: str = ""  # path or URL
    tags: List[str] = Field(default_factory=list)
    license_note: str = ""
    provenance: str = ""  # generation provenance if relevant
    hash: str = ""  # content hash for dedup
    reuse_count: int = Field(default=0, ge=0)
    # Semantic embedding is stored in meta["embedding"] (JSON) so it round-trips
    # through the asset table without a dedicated column.
    meta: Dict[str, Any] = Field(default_factory=dict)

    def semantic_text(self) -> str:
        """Searchable text for embedding: uri stem + tags."""
        import os

        stem = ""
        if self.uri:
            stem = os.path.basename(self.uri.rstrip("/")).split(".")[0]
        return " ".join([stem] + list(self.tags))
