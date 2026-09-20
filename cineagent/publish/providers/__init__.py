"""Concrete publishers. All default to dry-run; spec is enforced by base."""

from __future__ import annotations

from ..base import PublishRequest, PublishResult, Publisher


def _unconfigured(name: str):
    async def _post(self, req, pid):
        raise RuntimeError(
            f"{name} is declared but its API integration is 'planned'. "
            "To enable, implement _post() with the platform's official API. "
            "Dry-run validation still runs (default).")
    return _post


class YouTubePublisher(Publisher):
    platform = "youtube"
    _post = _unconfigured("YouTubePublisher")


class TikTokPublisher(Publisher):
    platform = "tiktok"
    _post = _unconfigured("TikTokPublisher")


class InstagramPublisher(Publisher):
    platform = "instagram"
    _post = _unconfigured("InstagramPublisher")


class XPublisher(Publisher):
    platform = "x"
    _post = _unconfigured("XPublisher")


class TelegramPublisher(Publisher):
    platform = "telegram"
    _post = _unconfigured("TelegramPublisher")
