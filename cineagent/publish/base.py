"""Publisher contract + base + concrete dry-run implementers.

Rule: a publisher is only "declared" if it validates specs/metadata, has a
dry-run, persists the remote post ID, and distinguishes failed/published.
Default is dry-run; it never publishes without explicit configuration.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..storage.database import Database
from ..storage.repositories import PublishRepo


@dataclass
class PublishRequest:
    project_id: str
    video_path: str
    platform: str
    title: str = ""
    caption: str = ""
    tags: List[str] = field(default_factory=list)
    publish_id: str = ""
    credentials: Optional[dict] = None  # never logged as plaintext


@dataclass
class PublishResult:
    publish_id: str
    status: str = "pending"  # published | failed | dry_run
    remote_post_id: str = ""
    error: str = ""


class Publisher(ABC):
    platform: str = "base"

    def __init__(self, dry_run: bool = True, repo: Optional[PublishRepo] = None) -> None:
        self.dry_run = dry_run
        self.repo = repo

    def validate_video_spec(self, video_path: str) -> List[str]:
        """Return a list of spec violations (empty = ok)."""
        from ..media.ffmpeg import probe_video
        try:
            info = probe_video(video_path)
        except Exception as e:  # noqa: BLE001 - surfaced as a violation list
            return [f"cannot probe video: {e}"]
        problems: List[str] = []
        if not info.get("duration", 0) > 0:
            problems.append("video has no duration")
        return problems

    def validate_metadata(self, req: PublishRequest) -> List[str]:
        problems: List[str] = []
        if not req.title and not req.caption:
            problems.append("no title or caption provided")
        return problems

    async def publish(self, req: PublishRequest) -> PublishResult:
        pid = req.publish_id or _new_publish_id(req.project_id, self.platform)
        spec_problems = self.validate_video_spec(req.video_path)
        meta_problems = self.validate_metadata(req)
        problems = spec_problems + meta_problems
        if problems:
            result = PublishResult(publish_id=pid, status="failed",
                                   error="; ".join(problems))
            if self.repo:
                self.repo.upsert(pid, req.project_id, self.platform, None,
                                 "failed", req.video_path, result.error)
            return result
        if self.dry_run:
            result = PublishResult(publish_id=pid, status="dry_run",
                                   remote_post_id="")
            if self.repo:
                self.repo.upsert(pid, req.project_id, self.platform, None,
                                 "dry_run", req.video_path,
                                 "dry-run: not published")
            return result
        # Real publish (only when explicitly configured, not default)
        return await self._post(req, pid)

    @abstractmethod
    async def _post(self, req: PublishRequest, publish_id: str) -> PublishResult:
        raise NotImplementedError


def _new_publish_id(project_id: str, platform: str) -> str:
    import uuid
    return f"pub-{project_id}-{platform}-{uuid.uuid4().hex[:8]}"
