"""VisualBible — central, reference-first consistency authority."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class VisualCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    char_id: str
    name: str = ""
    appearance: str = ""  # sex/age/build/hair/face marks
    wardrobe: str = ""
    reference_assets: List[str] = Field(default_factory=list)
    continuity_notes: str = ""


class VisualBible(BaseModel):
    """Central store of everything that must stay consistent across shots."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    characters: Dict[str, VisualCharacter] = Field(default_factory=dict)
    wardrobe: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    props: List[str] = Field(default_factory=list)
    palette: List[str] = Field(default_factory=list)
    lighting: str = ""
    art_style: str = ""
    lens_language: str = ""
    camera_language: str = ""
    reference_assets: List[str] = Field(default_factory=list)
    negative_constraints: List[str] = Field(default_factory=list)
    continuity_rules: List[str] = Field(default_factory=list)

    def character(self, char_id: str) -> Optional[VisualCharacter]:
        return self.characters.get(char_id)
