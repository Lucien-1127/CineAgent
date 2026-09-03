"""Canonical domain models for CineAgent v4 (provider-independent)."""
from .asset import Asset
from .enums import (
    AssetSource,
    AssetType,
    CameraAngle,
    CameraMotion,
    GenerationStrategy,
    JobState,
    Language,
    OperationKind,
    Platform,
    ProjectStatus,
    QualityMode,
    QualityTier,
    ScriptStrategy,
    ShotSize,
    ShotState,
)
from .job import GenerationJob, QAReport
from .project import VideoProject
from .script import (
    CreativeBrief,
    CritiqueResult,
    Fact,
    HookCandidate,
    HookSet,
    Scene,
    ScriptPackage,
)
from .shot import ShotSpec
from .usage import UsageEvent
from .visual import VisualBible, VisualCharacter

__all__ = [
    "Asset",
    "AssetSource",
    "AssetType",
    "CameraAngle",
    "CameraMotion",
    "CreativeBrief",
    "CritiqueResult",
    "Fact",
    "GenerationJob",
    "GenerationStrategy",
    "HookCandidate",
    "HookSet",
    "JobState",
    "Language",
    "OperationKind",
    "Platform",
    "ProjectStatus",
    "QAReport",
    "QualityMode",
    "QualityTier",
    "Scene",
    "ScriptPackage",
    "ScriptStrategy",
    "ShotSize",
    "ShotSpec",
    "ShotState",
    "UsageEvent",
    "VideoProject",
    "VisualBible",
    "VisualCharacter",
]
