"""Model Capability Registry — capability-based, cost-aware model selection.

Vendor price/model facts here are ONLY populated after official-doc review;
unknown values are left None and treated as \"must be configured\". Never guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass(frozen=True)
class ModelCapability:
    provider: str
    model: str
    modalities: Tuple[str, ...] = ()          # text, image, video, audio
    supports: frozenset = frozenset()         # text_to_video, image_to_video, video_to_video,
                                              # first_frame, last_frame, reference_image,
                                              # reference_video, audio_generation
    max_duration: float = 0.0                 # seconds
    aspect_ratios: Tuple[str, ...] = ()
    resolution: str = ""
    concurrency: int = 1
    expected_latency_s: float = 0.0
    estimated_cost_usd: Optional[float] = None  # None = unknown, must configure
    reliability: float = 0.0                   # 0..1
    status: str = "planned"                    # implemented / experimental / planned

    def supports_all(self, required: Iterable[str]) -> bool:
        return all(r in self.supports for r in required)


class CapabilityRegistry:
    def __init__(self, models: Optional[List[ModelCapability]] = None) -> None:
        self._by_key: Dict[str, ModelCapability] = {}
        for m in (models or []):
            self.register(m)

    def register(self, m: ModelCapability) -> None:
        self._by_key[f"{m.provider}/{m.model}"] = m

    def get(self, provider: str, model: str) -> Optional[ModelCapability]:
        return self._by_key.get(f"{provider}/{model}")

    def all(self) -> List[ModelCapability]:
        return list(self._by_key.values())


def default_registry() -> CapabilityRegistry:
    """Registry with only the offline Mock provider (implemented).

    Real vendors (Kling/Runway/Veo/Sora/Luma/OrcaRouter) are added only after
    official-doc review, with real pricing/model fields — never guessed.
    """
    reg = CapabilityRegistry()
    reg.register(ModelCapability(
        provider="mock", model="mock-video",
        modalities=("video", "image", "text", "audio"),
        supports=frozenset({
            "text_to_video", "image_to_video", "video_to_video",
            "first_frame", "last_frame", "reference_image", "reference_video",
            "audio_generation",
        }),
        max_duration=60.0, aspect_ratios=("9:16", "16:9", "1:1"),
        resolution="1080p", concurrency=8, expected_latency_s=0.1,
        estimated_cost_usd=0.0, reliability=1.0, status="implemented",
    ))
    # Declared-but-not-implemented vendors (status: planned, cost unknown).
    for prov in ("kling", "runway", "veo", "sora", "luma", "orcarouter"):
        reg.register(ModelCapability(
            provider=prov, model=f"{prov}-video", status="planned",
        ))
    return reg


class NoCapableModelError(RuntimeError):
    pass


class ModelRouter:
    """Select provider+model (+fallback chain) from shot requirements & constraints."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def select(
        self,
        required_caps: Set[str],
        duration: float,
        aspect: str = "9:16",
        quality: str = "auto",
        budget: Optional[float] = None,
        allow_planned: bool = False,
    ) -> List[Tuple[str, str]]:
        """Return an ordered (provider, model) chain; raises if none is viable."""
        viable: List[ModelCapability] = []
        for m in self.registry.all():
            if m.status == "planned" and not allow_planned:
                continue
            if not m.supports_all(required_caps):
                continue
            if duration > m.max_duration:
                continue
            if aspect not in m.aspect_ratios:
                continue
            if m.estimated_cost_usd is None:
                continue  # cost unknown => don't silently pick an unbudgeted model
            if budget is not None and m.estimated_cost_usd > budget:
                continue
            viable.append(m)
        if not viable:
            raise NoCapableModelError(
                f"no model satisfies caps={sorted(required_caps)} dur={duration} "
                f"aspect={aspect} budget={budget}"
            )
        # cost-aware ordering (cheapest feasible first)
        viable.sort(key=lambda m: (m.estimated_cost_usd or 0.0, -m.reliability))
        return [(m.provider, m.model) for m in viable]
