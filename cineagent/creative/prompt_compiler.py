"""PromptCompiler — ShotSpec -> provider-facing prompt payload.

This module keeps vendor prompt formats OUT of the business/creative layer.
Vendor-specific compilers live here and are keyed by provider name; unregistered
vendor compilers raise (never guess payload formats).
"""
from __future__ import annotations

from typing import Dict, Optional

from ..domain.shot import ShotSpec
from ..providers.base import ProviderError


class VendorNotImplemented(ProviderError):
    """Raised when a vendor compiler is not yet implemented (planned)."""


def compile_default(shot: ShotSpec, negative: Optional[list] = None) -> Dict:
    """Provider-neutral baseline payload. Adapters may consume or transform it."""
    scene = " ".join(s for s in [shot.subject, shot.action, shot.location] if s)
    cam = f", {shot.camera_motion.value} camera"
    if shot.camera_motion.value == "static":
        cam = ""
    return {
        "prompt_text": f"{scene}{cam}, {shot.composition}".strip(),
        "negative": negative or [],
        "aspect": {"shot_size": shot.shot_size.value},
        "origin": "ShotSpec",
        "shot_id": shot.shot_id,
    }


class PromptCompiler:
    """Route a ShotSpec to the right vendor compiler by provider name."""

    VENDOR_COMPILERS: Dict[str, str] = {
        # Declared (status: planned) — compilers are written only after official
        # API-doc review, NEVER guessed. Calling an unimplemented vendor raises.
        "kling": "planned",
        "runway": "planned",
        "veo": "planned",
        "sora": "planned",
        "luma": "planned",
        "orcarouter": "planned",
    }

    def compile(self, shot: ShotSpec, provider_name: str,
                negative: Optional[list] = None) -> Dict:
        if provider_name in self.VENDOR_COMPILERS:
            raise VendorNotImplemented(
                f"vendor compiler '{provider_name}' is declared but not yet implemented"
            )
        return compile_default(shot, negative=negative)
