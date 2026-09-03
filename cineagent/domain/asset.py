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
    # Semantic embedding (plug-in). Offline fallback is a coarse hash-vector.
    embedding: List[float] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    license_note: str = ""
    provenance: str = ""  # generation provenance if relevant
    hash: str = ""  # content hash for dedup
    reuse_count: int = Field(default=0, ge=0)
    meta: Dict[str, Any] = Field(default_factory=dict)
