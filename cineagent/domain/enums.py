"""Canonical enums for CineAgent v4 domain models (provider-independent)."""
from __future__ import annotations

from enum import Enum


# ── Project ──────────────────────────────────────────────
class Platform(str, Enum):
    SHORTS = "shorts"
    REELS = "reels"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    X = "x"
    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"


class Language(str, Enum):
    ZH_TW = "zh-TW"
    EN = "en"
    ZH_CN = "zh-CN"


class QualityMode(str, Enum):
    DRAFT = "draft"
    AUTO = "auto"
    CINEMATIC = "cinematic"


class ProjectStatus(str, Enum):
    DRAFTING = "drafting"
    IN_PRODUCTION = "in_production"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    FAILED = "failed"


# ── Script ───────────────────────────────────────────────
class ScriptStrategy(str, Enum):
    SHORT_VIRAL = "short_viral"
    EDUCATIONAL = "educational"
    STORYTELLING = "storytelling"
    PRODUCT_AD = "product_ad"
    EXPLAINER = "explainer"
    DOCUMENTARY = "documentary"
    CINEMATIC = "cinematic"


# ── Shot / Generation ────────────────────────────────────
class ShotState(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    GENERATING = "generating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    APPROVED = "approved"
    REJECTED = "rejected"


class ShotSize(str, Enum):
    EXTREME_CLOSE_UP = "extreme_close_up"
    CLOSE_UP = "close_up"
    MEDIUM = "medium"
    MEDIUM_CLOSE_UP = "medium_close_up"
    FULL = "full"
    WIDE = "wide"
    EXTREME_WIDE = "extreme_wide"


class CameraAngle(str, Enum):
    EYE_LEVEL = "eye_level"
    LOW_ANGLE = "low_angle"
    HIGH_ANGLE = "high_angle"
    BIRDS_EYE = "birds_eye"
    OVER_THE_SHOULDER = "over_the_shoulder"


class CameraMotion(str, Enum):
    STATIC = "static"
    PAN = "pan"
    TILT = "tilt"
    TRACK = "track"
    DOLLY = "dolly"
    HANDHELD = "handheld"
    PUSH_IN = "push_in"
    PULL_OUT = "pull_out"


class GenerationStrategy(str, Enum):
    REUSE_FROM_LIBRARY = "reuse_from_library"
    STOCK = "stock"
    EXISTING_GENERATED = "existing_generated"
    GENERATED_IMAGE = "generated_image"
    IMAGE_TO_VIDEO = "image_to_video"
    TEXT_TO_VIDEO = "text_to_video"
    VIDEO_TO_VIDEO = "video_to_video"
    PREMIUM_VIDEO = "premium_video"


class QualityTier(str, Enum):
    LOW = "low"      # draft / fast
    BALANCED = "balanced"  # auto
    CINEMATIC = "cinematic"


# ── Assets ───────────────────────────────────────────────
class AssetSource(str, Enum):
    LIBRARY = "library"
    STOCK = "stock"
    GENERATED = "generated"
    PROJECT = "project"


class AssetType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"


# ── Jobs ─────────────────────────────────────────────────
class JobState(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    GENERATING = "generating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    APPROVED = "approved"
    REJECTED = "rejected"


class OperationKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    RENDER = "render"
    QA = "qa"
