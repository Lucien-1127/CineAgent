"""Model routing for CineAgent v4.

Everything here is capability-first: a task asks for a *capability*
(``video``, ``image``, ``vlm``, ``llm``) and a *tier* (``best`` / ``budget``),
and the router returns the first model that is both listed by the provider
and healthy right now.

Probed on 2026-11-19 against api.orcarouter.ai and openrouter.ai:

* video  → OrcaRouter ``kling/*`` (``/v1/video/generations``, async) and
           ``minimax/minimax-h3``. OpenRouter's video models live on a
           *different* endpoint (``/api/v1/videos``), so both are modelled.
* image  → OrcaRouter ``/v1/images/generations`` accepts **imagen only**
           (it rejects gemini/gpt-image with "only imagen models are
           supported"). OpenRouter exposes ``google/gemini-nano-banana-*``
           through chat completions, but image output needs >= $1 balance.
* vlm    → OpenRouter ``anthropic/claude-haiku-5.5`` answered a vision probe;
           OrcaRouter ``orcarouter/fusion`` and ``orcarouter/pod`` did too,
           while ``google/gemini-*`` / ``anthropic/claude-*`` / ``openai/gpt-*``
           on OrcaRouter returned 503 upstream_unavailable.
* llm    → ``orcarouter/fusion`` (routes to a fast MoE) and ``orcarouter/pod``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ORCAROUTER_BASE = os.environ.get("ORCAROUTER_BASE", "https://api.orcarouter.ai/v1")
OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")

ORCAROUTER_KEY_ENVS = ("HERMES_CUSTOM_API_ORCAROUTER_AI_API_KEY", "ORCAROUTER_API_KEY")
OPENROUTER_KEY_ENVS = ("OPENROUTER_API_KEY", "OPENROUTER_KEY")

CACHE_FILE = Path(os.environ.get("CINE_MODEL_CACHE", Path.home() / ".cache/cineagent/models.json"))
CACHE_TTL = int(os.environ.get("CINE_MODEL_CACHE_TTL", "600"))

HERMES_ENV_FILES = (
    Path.home() / ".hermes" / ".env",
    Path.home() / ".config" / "hermes" / ".env",
)


def load_env(paths: Iterable[Path] = HERMES_ENV_FILES) -> None:
    """Load API keys from Hermes' .env without overriding existing vars."""
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _first_env(names: Iterable[str]) -> tuple[str, str]:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return name, value
    return "", ""


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str            # "orcarouter" | "openrouter"
    capability: str          # video | image | vlm | llm
    tier: str                # best | balanced | budget
    note: str = ""
    first_last_frame: bool = False   # native first-frame + last-frame anchoring
    multi_reference: bool = False    # image_list / video_list omni surface
    max_duration: int = 0            # seconds, 0 = n/a
    endpoint: str = ""               # provider-specific route
    durations: tuple[int, ...] = (5, 10)   # durations the model actually accepts

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.id}"


VIDEO_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("kling/kling-v3-omni", "orcarouter", "video", "best",
              "Kling 3.0 Omni — full omni surface: image_list first/end frame, "
              "video reference, 3-15s, 4K, native audio",
              first_last_frame=True, multi_reference=True, max_duration=15,
              endpoint="/video/generations", durations=tuple(range(3, 16))),
    ModelSpec("kling/kling-v3", "orcarouter", "video", "best",
              "Kling 3.0 — multi-shot, subject + motion control, 3-15s, 4K",
              first_last_frame=True, max_duration=15, endpoint="/video/generations",
              durations=tuple(range(3, 16))),
    ModelSpec("kling/kling-video-o1", "orcarouter", "video", "balanced",
              "Kling O1 — omni subset, 5s/10s only, no multi-shot",
              first_last_frame=True, multi_reference=True, max_duration=10,
              endpoint="/video/generations"),
    ModelSpec("kling/kling-v2-6", "orcarouter", "video", "budget",
              "Kling 2.6 — i2v + motion/audio control, 1080p, 5s/10s",
              first_last_frame=True, max_duration=10, endpoint="/video/generations"),
    ModelSpec("kling/kling-v2-5-turbo", "orcarouter", "video", "budget",
              "Kling 2.5 Turbo — cheapest live route, 5s/10s",
              first_last_frame=True, max_duration=10, endpoint="/video/generations"),
    ModelSpec("kling/kling-3-turbo", "orcarouter", "video", "budget",
              "Kling 3 Turbo — $0.112/request, cheapest Kling 3 route",
              first_last_frame=True, max_duration=10, endpoint="/video/generations"),
    ModelSpec("kling/kling-v2-master", "orcarouter", "video", "balanced",
              "Kling 2 Master — $0.28/request, high-fidelity 2.x",
              first_last_frame=True, max_duration=10, endpoint="/video/generations"),
    ModelSpec("minimax/minimax-h3", "orcarouter", "video", "balanced",
              "MiniMax-H3 — omni-modal video, audio support",
              first_last_frame=True, max_duration=10, endpoint="/video/generations"),
    ModelSpec("google/veo-3.1", "openrouter", "video", "best",
              "Veo 3.1 via OpenRouter async videos API (4/6/8s)",
              first_last_frame=True, max_duration=8, endpoint="/videos",
              durations=(4, 6, 8)),
    ModelSpec("kwaivgi/kling-v3.0-pro", "openrouter", "video", "balanced",
              "Kling v3.0 Pro via OpenRouter videos API",
              first_last_frame=True, max_duration=10, endpoint="/videos"),
    ModelSpec("alibaba/wan-3.0", "openrouter", "video", "budget",
              "Wan 3.0 via OpenRouter videos API", first_last_frame=True,
              max_duration=10, endpoint="/videos"),
    ModelSpec("google/veo-3.1-fast", "openrouter", "video", "balanced",
              "Veo 3.1 Fast — cheaper Veo tier", first_last_frame=True,
              max_duration=8, endpoint="/videos", durations=(4, 6, 8)),
    ModelSpec("kwaivgi/kling-v3.0-std", "openrouter", "video", "budget",
              "Kling 3.0 Std — OpenRouter budget tier",
              first_last_frame=True, max_duration=10, endpoint="/videos"),
    ModelSpec("bytedance/seedance-2.5", "openrouter", "video", "balanced",
              "Seedance 2.5 — strong motion coherence",
              first_last_frame=True, max_duration=10, endpoint="/videos"),
    ModelSpec("minimax/hailuo-3-max", "openrouter", "video", "balanced",
              "Hailuo 3 Max — expressive camera motion",
              first_last_frame=True, max_duration=10, endpoint="/videos"),
    ModelSpec("black-forest-labs/flux-3-video", "openrouter", "video", "budget",
              "FLUX 3 Video — the only FLUX route available (video, not stills)",
              first_last_frame=True, max_duration=10, endpoint="/videos"),
)

IMAGE_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("google/imagen-4.0-generate-001", "orcarouter", "image", "best",
              "Imagen 4 — 1024px+, n + aspect_ratio + size", endpoint="/images/generations"),
    ModelSpec("google/imagen-4.0-ultra-generate-001", "orcarouter", "image", "best",
              "Imagen 4 Ultra — highest fidelity, priciest", endpoint="/images/generations"),
    ModelSpec("google/imagen-4.0-fast-generate-001", "orcarouter", "image", "budget",
              "Imagen 4 Fast — cheapest still", endpoint="/images/generations"),
    ModelSpec("google/gemini-3.1-flash-image", "openrouter", "image", "balanced",
              "Nano-banana flash image via chat modalities (needs >= $1 balance)",
              endpoint="/chat/completions"),
    ModelSpec("google/gemini-3-pro-image", "openrouter", "image", "best",
              "Gemini 3 Pro Image — best prompt adherence (needs >= $1 balance)",
              endpoint="/chat/completions"),
    ModelSpec("openai/gpt-5-image-mini", "openrouter", "image", "budget",
              "GPT-image mini via chat modalities (needs >= $1 balance)",
              endpoint="/chat/completions"),
)

# Imagen only on OrcaRouter's images route — kept separate so the router can
# explain why a gemini/gpt-image request is not attempted there.
UNSUPPORTED_IMAGE_ROUTES = {
    "google/gemini-2.5-flash-image": "OrcaRouter /images/generations is imagen-only "
                                     "(API returns 'only imagen models are supported')",
    "openai/gpt-image-1.5": "same route, imagen-only",
}

VLM_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("anthropic/claude-haiku-5.5", "openrouter", "vlm", "balanced",
              "verified vision probe: answered a one-word image question", endpoint="/chat/completions"),
    ModelSpec("anthropic/claude-sonnet-5.5", "openrouter", "vlm", "best",
              "higher-fidelity visual judgement", endpoint="/chat/completions"),
    ModelSpec("orcarouter/fusion", "orcarouter", "vlm", "balanced",
              "verified vision probe; routes to a fast MoE", endpoint="/chat/completions"),
    ModelSpec("orcarouter/pod", "orcarouter", "vlm", "budget",
              "verified vision probe, reasoning visible", endpoint="/chat/completions"),
    ModelSpec("google/gemini-3.5-flash", "orcarouter", "vlm", "balanced",
              "503 upstream_unavailable at probe time — last resort", endpoint="/chat/completions"),
)

LLM_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("orcarouter/fusion", "orcarouter", "llm", "balanced",
              "structured JSON planning, fast", endpoint="/chat/completions"),
    ModelSpec("orcarouter/pod", "orcarouter", "llm", "balanced",
              "reasoning-heavy planning", endpoint="/chat/completions"),
    ModelSpec("anthropic/claude-haiku-5.5", "openrouter", "llm", "budget",
              "cheap drafting", endpoint="/chat/completions"),
    ModelSpec("anthropic/claude-sonnet-5.5", "openrouter", "llm", "best",
              "best prose + shot logic", endpoint="/chat/completions"),
)

REGISTRY: dict[str, tuple[ModelSpec, ...]] = {
    "video": VIDEO_MODELS,
    "image": IMAGE_MODELS,
    "vlm": VLM_MODELS,
    "llm": LLM_MODELS,
}


class RoutingError(RuntimeError):
    """No healthy model for the requested capability."""


def snap_duration(spec: ModelSpec, seconds: float) -> int:
    """Round a duration to a value the model actually accepts.

    Kling 2.x only takes 5 or 10 seconds, Kling 3.x takes 3-15, Veo takes 4/6/8.
    Sending 4 to Kling 2.6 returns ``duration value '4' is invalid``.
    """
    allowed = spec.durations or (5, 10)
    return min(allowed, key=lambda value: abs(value - seconds))


def provider_base(provider: str) -> str:
    return {"orcarouter": ORCAROUTER_BASE, "openrouter": OPENROUTER_BASE}[provider]


def provider_key(provider: str) -> str:
    names = ORCAROUTER_KEY_ENVS if provider == "orcarouter" else OPENROUTER_KEY_ENVS
    name, value = _first_env(names)
    if not value:
        raise RoutingError(
            f"missing API key for {provider}; set one of {', '.join(names)}"
        )
    return value


def _http_json(url: str, key: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                 "User-Agent": "cineagent/4.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_catalog(provider: str, refresh: bool = False) -> dict:
    """Return ``{model_id: raw_metadata}`` for one provider (cached on disk)."""
    cache = {}
    if CACHE_FILE.exists() and not refresh:
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}
    entry = cache.get(provider)
    if entry and not refresh and (time.time() - entry.get("fetched_at", 0)) < CACHE_TTL:
        return entry.get("models", {})

    key = provider_key(provider)
    raw: list[dict] = []
    if provider == "orcarouter":
        raw = _http_json(ORCAROUTER_BASE + "/models", key).get("data", [])
    else:
        raw = _http_json(OPENROUTER_BASE + "/models", key).get("data", [])
        # Video models live on a separate endpoint.
        try:
            vids = _http_json(OPENROUTER_BASE + "/videos/models", key)
            raw = list(raw) + list(vids.get("data", []) if isinstance(vids, dict) else vids)
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
            pass

    models = {m.get("id", ""): m for m in raw if m.get("id")}
    cache[provider] = {"fetched_at": time.time(), "models": models}
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return models


def _health(spec: ModelSpec, catalog: dict) -> tuple[bool, str]:
    meta = catalog.get(spec.id)
    if not meta:
        return False, "not listed by provider"
    caps = meta.get("endpoint_capabilities") or []
    if not caps:
        # OpenRouter publishes output modalities, not endpoint capabilities.
        caps = (meta.get("architecture") or {}).get("output_modalities") or []
    need = {"video": "video_generation", "image": "image_generation"}.get(spec.capability)
    if need and caps:
        accepted = {need, "image" if need == "image_generation" else need,
                    "video" if need == "video_generation" else need}
        if not (accepted & set(caps)):
            return False, f"provider lists capabilities={caps}"
    return True, "ok"


@dataclass
class RouteDecision:
    spec: ModelSpec
    base_url: str
    api_key: str
    checked: list[str] = field(default_factory=list)


class Router:
    """Capability router with live catalog checks and deterministic fallbacks."""

    def __init__(self, refresh: bool = False, probes: dict[str, bool] | None = None):
        self.refresh = refresh
        self.probes = probes or {}
        self._catalogs: dict[str, dict] = {}

    def catalog(self, provider: str) -> dict:
        if provider not in self._catalogs:
            try:
                data = fetch_catalog(provider, self.refresh)
                # A stale/empty on-disk cache must never disable the whole router.
                if not data:
                    data = fetch_catalog(provider, True)
                self._catalogs[provider] = data
            except (RoutingError, urllib.error.URLError, urllib.error.HTTPError,
                    json.JSONDecodeError) as exc:
                self._catalogs[provider] = {}
                self.probes.setdefault(provider, False)
                self.probes[f"{provider}:error"] = str(exc)  # type: ignore[assignment]
        return self._catalogs[provider]

    def candidates(self, capability: str, tier: str = "best") -> list[ModelSpec]:
        specs = REGISTRY[capability]
        # Requested tier first, then the usual degradation path. Built as a list
        # so a tier never collides with itself in the rank map.
        preference = [tier] + [t for t in ("best", "balanced", "budget") if t != tier]
        rank = {t: i for i, t in enumerate(preference)}
        seen, out = set(), []
        for spec in specs:
            if spec.key in seen:
                continue
            seen.add(spec.key)
            out.append(spec)
        # Declaration order is the preference order inside a tier (Kling Omni
        # before Kling v3 before the OpenRouter fallbacks), so keep it stable.
        decl = {spec.key: i for i, spec in enumerate(out)}
        return sorted(out, key=lambda s: (rank.get(s.tier, 99), decl[s.key]))

    def resolve(self, capability: str, tier: str = "best") -> RouteDecision:
        checked: list[str] = []
        for spec in self.candidates(capability, tier):
            ok, why = _health(spec, self.catalog(spec.provider))
            checked.append(f"{spec.key}: {why}")
            if not ok:
                continue
            return RouteDecision(spec, provider_base(spec.provider),
                                 provider_key(spec.provider), checked)
        raise RoutingError(
            f"no healthy {capability} model.\n  " + "\n  ".join(checked)
        )

    def resolve_all(self, capability: str, tier: str = "best") -> list[RouteDecision]:
        """Every healthy route, in preference order (used for image fallback)."""
        decisions: list[RouteDecision] = []
        for spec in self.candidates(capability, tier):
            ok, _ = _health(spec, self.catalog(spec.provider))
            if not ok:
                continue
            try:
                decisions.append(RouteDecision(spec, provider_base(spec.provider),
                                               provider_key(spec.provider), []))
            except RoutingError:
                continue
        if not decisions:
            raise RoutingError(f"no healthy {capability} model for fallback chain")
        return decisions

    def report(self) -> dict:
        out = {}
        for capability in REGISTRY:
            rows = []
            for spec in REGISTRY[capability]:
                ok, why = _health(spec, self.catalog(spec.provider))
                rows.append({"model": spec.key, "tier": spec.tier,
                             "listed": ok, "detail": why,
                             "first_last_frame": spec.first_last_frame})
            out[capability] = rows
        return out
