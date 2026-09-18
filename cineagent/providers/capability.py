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


def _seedance_caps() -> List[ModelCapability]:
    """Verified Seedance entries (official tutorial docs.volcengine.com/82379/2298881).

    estimated_cost_usd stays None (pricing UNVERIFIED), so the cost-aware
    ModelRouter will not auto-select them until a real price is configured;
    the planner addresses them directly by provider/model.
    """
    base = {"text_to_video", "image_to_video", "first_frame", "last_frame"}
    ref = base | {"reference_image", "reference_video", "reference_audio"}

    def m(model: str, max_dur: float, supports, audio: bool) -> ModelCapability:
        caps = set(supports)
        if audio:
            caps.add("audio_generation")
        return ModelCapability(
            provider="seedance", model=model, modalities=("video",),
            supports=frozenset(caps), max_duration=max_dur,
            aspect_ratios=("16:9", "9:16", "1:1", "21:9", "adaptive"),
            resolution="1080p", concurrency=1, expected_latency_s=60.0,
            estimated_cost_usd=None, reliability=0.5, status="experimental",
        )

    return [
        m("doubao-seedance-2-5-260628", 30.0, ref, True),
        m("doubao-seedance-2-0-260128", 15.0, ref, True),
        m("doubao-seedance-2-0-fast-260128", 15.0, ref, True),
        m("doubao-seedance-2-0-mini-260615", 15.0, ref, True),
        m("doubao-seedance-1-5-pro-251215", 12.0, base, True),
        m("doubao-seedance-1-0-pro-250528", 12.0, base, False),
        m("doubao-seedance-1-0-pro-fast-251015", 12.0,
          {"text_to_video", "image_to_video", "first_frame"}, False),
    ]


def _kling_caps() -> List[ModelCapability]:
    """Kling legacy API entries. max_duration is conservative (5/10s enum).

    kling-v2-1 / kling-v2-1-master are image-to-video only. Native audio is
    only cross-confirmed for kling-v2-6 and kling-v3.
    """
    i2v = {"image_to_video", "first_frame", "last_frame"}
    base = i2v | {"text_to_video"}

    def m(model: str, supports, audio: bool) -> ModelCapability:
        caps = set(supports)
        if audio:
            caps.add("audio_generation")
        return ModelCapability(
            provider="kling", model=model, modalities=("video",),
            supports=frozenset(caps), max_duration=10.0,
            aspect_ratios=("16:9", "9:16", "1:1", "4:3", "3:4", "21:9"),
            resolution="1080p", concurrency=1, expected_latency_s=60.0,
            estimated_cost_usd=None, reliability=0.5, status="experimental",
        )

    return [
        m("kling-v1", base, False),
        m("kling-v1-5", base, False),
        m("kling-v1-6", base, False),
        m("kling-v2", base, False),
        m("kling-v2-master", base, False),
        m("kling-v2-5", base, False),
        m("kling-v2-5-turbo", base, False),
        m("kling-v2-6", base, True),
        m("kling-v3", base, True),
        m("kling-v2-1", i2v, False),
        m("kling-v2-1-master", i2v, False),
    ]


def default_registry() -> CapabilityRegistry:
    """Registry of implemented (mock) + experimental (Seedance/Kling) providers.

    Seedance and Kling are registered with verified capability fields and
    status "experimental" (adapters implemented, not yet live-verified).
    Real prices are left None so the cost-aware router never silently picks an
    unpriced model. Remaining vendors stay "planned".
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
    for cap in _seedance_caps():
        reg.register(cap)
    for cap in _kling_caps():
        reg.register(cap)
    from .video.orcarouter import KLING_MODELS, SEEDANCE, duration_policy
    for model in sorted(KLING_MODELS | {SEEDANCE}):
        supports = {"text_to_video", "image_to_video", "first_frame", "last_frame"}
        if model == SEEDANCE:
            supports |= {"reference_image", "reference_video", "reference_audio", "audio_generation"}
        elif model in ("kling/kling-video-o1", "kling/kling-v3-omni"):
            supports |= {"reference_image", "reference_video"}
        if model in ("kling/kling-v3", "kling/kling-v3-omni", "kling/kling-v2-6"):
            supports.add("audio_generation")
        reg.register(ModelCapability(
            provider="orcarouter", model=model, modalities=("video",),
            supports=frozenset(supports), max_duration=duration_policy(model)[1],
            aspect_ratios=("16:9", "9:16", "1:1"), resolution="1080p",
            estimated_cost_usd=None, status="experimental"))
    # Declared-but-not-implemented vendors (status: planned, cost unknown).
    for prov in ("runway", "veo", "sora", "luma"):
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
