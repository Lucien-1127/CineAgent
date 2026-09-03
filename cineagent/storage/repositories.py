"""Repositories — CRUD + ledger over the SQLite store."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..domain.asset import Asset
from ..domain.job import GenerationJob
from ..domain.project import VideoProject
from ..domain.usage import UsageEvent
from .database import Database, SCHEMA


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(db: Database) -> None:
    db.conn.executescript(SCHEMA)
    db.commit()


# ── Projects ─────────────────────────────────────────────
class ProjectRepo:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, p: VideoProject) -> VideoProject:
        self.db.execute(
            """INSERT INTO projects
               (project_id, topic, objective, audience, platform, language,
                target_duration, aspect_ratio, quality_mode, budget_limit, status, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(project_id) DO UPDATE SET
                 topic=excluded.topic, objective=excluded.objective,
                 audience=excluded.audience, platform=excluded.platform,
                 language=excluded.language, target_duration=excluded.target_duration,
                 aspect_ratio=excluded.aspect_ratio, quality_mode=excluded.quality_mode,
                 budget_limit=excluded.budget_limit, status=excluded.status,
                 updated_at=excluded.updated_at""",
            (
                p.project_id, p.topic, p.objective, p.audience, p.platform.value,
                p.language.value, p.target_duration, p.aspect_ratio,
                p.quality_mode.value, p.budget_limit, p.status.value, _utcnow(),
            ),
        )
        self.db.commit()
        return p

    def get(self, project_id: str) -> Optional[VideoProject]:
        row = self.db.execute(
            "SELECT * FROM projects WHERE project_id=?", (project_id,)
        ).fetchone()
        if not row:
            return None
        return VideoProject(
            project_id=row["project_id"], topic=row["topic"],
            objective=row["objective"] or "", audience=row["audience"] or "",
            platform=row["platform"], language=row["language"],
            target_duration=row["target_duration"], aspect_ratio=row["aspect_ratio"],
            quality_mode=row["quality_mode"], budget_limit=row["budget_limit"],
            status=row["status"],
        )

    def list(self) -> List[VideoProject]:
        rows = self.db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        out = []
        for r in rows:
            out.append(self.get(r["project_id"]))  # type: ignore[arg-type]
        return [o for o in out if o is not None]


# ── Shots ────────────────────────────────────────────────
class ShotRepo:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, shot: Dict[str, Any]) -> None:
        self.db.execute(
            """INSERT INTO shots
               (shot_id, project_id, scene_id, start_time, end_time, duration,
                narration_segment, subject, action, shot_size, camera_angle,
                camera_motion, generation_strategy, quality_tier, state, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(shot_id) DO UPDATE SET
                 start_time=excluded.start_time, end_time=excluded.end_time,
                 duration=excluded.duration, narration_segment=excluded.narration_segment,
                 subject=excluded.subject, action=excluded.action,
                 shot_size=excluded.shot_size, camera_angle=excluded.camera_angle,
                 camera_motion=excluded.camera_motion,
                 generation_strategy=excluded.generation_strategy,
                 quality_tier=excluded.quality_tier, state=excluded.state,
                 updated_at=excluded.updated_at""",
            (
                shot["shot_id"], shot.get("project_id", ""), shot["scene_id"],
                shot.get("start_time"), shot.get("end_time"), shot.get("duration"),
                shot.get("narration_segment"), shot.get("subject"), shot.get("action"),
                shot.get("shot_size"), shot.get("camera_angle"),
                shot.get("camera_motion"), shot.get("generation_strategy"),
                shot.get("quality_tier"), shot.get("state", "pending"), _utcnow(),
            ),
        )
        self.db.commit()

    def set_state(self, shot_id: str, state: str) -> None:
        self.db.execute(
            "UPDATE shots SET state=?, updated_at=? WHERE shot_id=?",
            (state, _utcnow(), shot_id),
        )
        self.db.commit()

    def get(self, shot_id: str) -> Optional[Dict[str, Any]]:
        row = self.db.execute("SELECT * FROM shots WHERE shot_id=?", (shot_id,)).fetchone()
        return dict(row) if row else None

    def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM shots WHERE project_id=? ORDER BY start_time", (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def states_for_project(self, project_id: str) -> Dict[str, str]:
        rows = self.db.execute(
            "SELECT shot_id, state FROM shots WHERE project_id=?", (project_id,)
        ).fetchall()
        return {r["shot_id"]: r["state"] for r in rows}


# ── Assets ───────────────────────────────────────────────
class AssetRepo:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, a: Asset) -> Asset:
        self.db.execute(
            """INSERT INTO assets
               (asset_id, project_id, source, type, uri, tags, license_note,
                provenance, hash, reuse_count, meta)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(asset_id) DO UPDATE SET
                 uri=excluded.uri, tags=excluded.tags, reuse_count=excluded.reuse_count,
                 provenance=excluded.provenance, meta=excluded.meta""",
            (
                a.asset_id, a.project_id, a.source.value, a.type.value, a.uri,
                json.dumps(a.tags, ensure_ascii=False), a.license_note,
                a.provenance, a.hash, a.reuse_count,
                json.dumps(a.meta, ensure_ascii=False),
            ),
        )
        self.db.commit()
        return a

    def find_by_hash(self, content_hash: str) -> Optional[Asset]:
        row = self.db.execute(
            "SELECT * FROM assets WHERE hash=?", (content_hash,)
        ).fetchone()
        return self._from_row(row) if row else None

    def find_by_tags(self, tags: List[str]) -> List[Asset]:
        # naive: substring match on the JSON tag string
        rows = self.db.execute("SELECT * FROM assets").fetchall()
        hits = []
        for r in rows:
            asset_tags = json.loads(r["tags"] or "[]")
            if set(tags) & set(asset_tags):
                hits.append(self._from_row(r))
        return hits

    def increment_reuse(self, asset_id: str) -> None:
        self.db.execute(
            "UPDATE assets SET reuse_count=reuse_count+1 WHERE asset_id=?", (asset_id,)
        )
        self.db.commit()

    def _from_row(self, r: Any) -> Asset:
        return Asset(
            asset_id=r["asset_id"], source=r["source"], type=r["type"],
            uri=r["uri"] or "", tags=json.loads(r["tags"] or "[]"),
            license_note=r["license_note"] or "", provenance=r["provenance"] or "",
            hash=r["hash"] or "", reuse_count=r["reuse_count"] or 0,
            meta=json.loads(r["meta"] or "{}"),
        )


# ── Jobs ─────────────────────────────────────────────────
class JobRepo:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, j: GenerationJob) -> GenerationJob:
        self.db.execute(
            """INSERT INTO jobs
               (job_id, project_id, scene_id, shot_id, provider, model, operation,
                remote_job_id, state, submitted_at, completed_at, retry_count,
                input_asset_ids, output_asset_ids, estimated_cost, actual_cost,
                error, payload)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(job_id) DO UPDATE SET
                 provider=excluded.provider, model=excluded.model,
                 remote_job_id=excluded.remote_job_id, state=excluded.state,
                 completed_at=excluded.completed_at, retry_count=excluded.retry_count,
                 input_asset_ids=excluded.input_asset_ids,
                 output_asset_ids=excluded.output_asset_ids,
                 estimated_cost=excluded.estimated_cost,
                 actual_cost=excluded.actual_cost, error=excluded.error,
                 payload=excluded.payload""",
            (
                j.job_id, j.project_id, j.scene_id, j.shot_id, j.provider, j.model,
                j.operation.value, j.remote_job_id, j.state.value,
                j.submitted_at.isoformat() if j.submitted_at else None,
                j.completed_at.isoformat() if j.completed_at else None,
                j.retry_count, json.dumps(j.input_asset_ids),
                json.dumps(j.output_asset_ids), j.estimated_cost, j.actual_cost,
                j.error, json.dumps(j.payload, ensure_ascii=False),
            ),
        )
        self.db.commit()
        return j

    def get(self, job_id: str) -> Optional[GenerationJob]:
        row = self.db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._from_row(row) if row else None

    def get_by_remote(self, remote_job_id: str) -> Optional[GenerationJob]:
        row = self.db.execute(
            "SELECT * FROM jobs WHERE remote_job_id=?", (remote_job_id,)
        ).fetchone()
        return self._from_row(row) if row else None

    def get_for_shot(self, shot_id: str) -> List[GenerationJob]:
        rows = self.db.execute(
            "SELECT * FROM jobs WHERE shot_id=? ORDER BY submitted_at", (shot_id,)
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def _from_row(self, r: Any) -> GenerationJob:
        return GenerationJob(
            job_id=r["job_id"], project_id=r["project_id"] or "",
            scene_id=r["scene_id"] or "", shot_id=r["shot_id"] or "",
            provider=r["provider"] or "", model=r["model"] or "",
            operation=r["operation"], remote_job_id=r["remote_job_id"],
            state=r["state"],
            submitted_at=r["submitted_at"], completed_at=r["completed_at"],
            retry_count=r["retry_count"] or 0,
            input_asset_ids=json.loads(r["input_asset_ids"] or "[]"),
            output_asset_ids=json.loads(r["output_asset_ids"] or "[]"),
            estimated_cost=r["estimated_cost"] or 0.0,
            actual_cost=r["actual_cost"] or 0.0, error=r["error"],
            payload=json.loads(r["payload"] or "{}"),
        )


# ── Usage / Cost Ledger ──────────────────────────────────
class UsageRepo:
    def __init__(self, db: Database):
        self.db = db

    def record(self, u: UsageEvent) -> UsageEvent:
        self.db.execute(
            """INSERT INTO usage_events
               (event_id, project_id, scene_id, shot_id, provider, model, operation,
                tokens_in, tokens_out, image_count, video_seconds, audio_seconds,
                retry, estimated_cost, actual_cost, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                u.event_id, u.project_id, u.scene_id, u.shot_id, u.provider, u.model,
                u.operation.value, u.tokens_in, u.tokens_out, u.image_count,
                u.video_seconds, u.audio_seconds, u.retry, u.estimated_cost,
                u.actual_cost, u.status, u.created_at.isoformat(),
            ),
        )
        self.db.commit()
        return u

    def _sum(self, sql: str, params: tuple = ()) -> float:
        row = self.db.execute(sql, params).fetchone()
        return float(row[0] or 0.0)

    def project_total(self, project_id: str) -> float:
        return self._sum(
            "SELECT SUM(actual_cost) FROM usage_events WHERE project_id=?",
            (project_id,),
        )

    def project_estimated(self, project_id: str) -> float:
        return self._sum(
            "SELECT SUM(estimated_cost) FROM usage_events WHERE project_id=?",
            (project_id,),
        )

    def cost_by_provider(self, project_id: str) -> Dict[str, float]:
        rows = self.db.execute(
            "SELECT provider, SUM(actual_cost) AS c FROM usage_events WHERE project_id=? GROUP BY provider",
            (project_id,),
        ).fetchall()
        return {r["provider"]: float(r["c"] or 0.0) for r in rows}

    def cost_by_model(self, project_id: str) -> Dict[str, float]:
        rows = self.db.execute(
            "SELECT model, SUM(actual_cost) AS c FROM usage_events WHERE project_id=? GROUP BY model",
            (project_id,),
        ).fetchall()
        return {r["model"]: float(r["c"] or 0.0) for r in rows}

    def cost_by_stage(self, project_id: str) -> Dict[str, float]:
        rows = self.db.execute(
            "SELECT operation, SUM(actual_cost) AS c FROM usage_events WHERE project_id=? GROUP BY operation",
            (project_id,),
        ).fetchall()
        return {r["operation"]: float(r["c"] or 0.0) for r in rows}

    def failed_cost(self, project_id: str) -> float:
        return self._sum(
            "SELECT SUM(actual_cost) FROM usage_events WHERE project_id=? AND status IN ('failed','billed_failed')",
            (project_id,),
        )


# ── QA reports / Publish ─────────────────────────────────
class QARepo:
    def __init__(self, db: Database):
        self.db = db

    def save(self, report) -> None:
        self.db.execute(
            """INSERT INTO qa_reports
               (shot_id, project_id, stage, score, threshold, decision,
                problems, severities, repair_instructions, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                report.shot_id, report.project_id, report.stage, report.score,
                report.threshold, report.decision,
                json.dumps(report.problems, ensure_ascii=False),
                json.dumps(report.severities, ensure_ascii=False),
                report.repair_instructions, report.created_at.isoformat(),
            ),
        )
        self.db.commit()

    def latest_for_shot(self, shot_id: str, stage: str) -> Optional[Dict[str, Any]]:
        row = self.db.execute(
            "SELECT * FROM qa_reports WHERE shot_id=? AND stage=? ORDER BY id DESC LIMIT 1",
            (shot_id, stage),
        ).fetchone()
        return dict(row) if row else None


class PublishRepo:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, publish_id: str, project_id: str, platform: str,
               remote_post_id: Optional[str], status: str, video_uri: str,
               error: Optional[str]) -> None:
        self.db.execute(
            """INSERT INTO publish_jobs
               (publish_id, project_id, platform, remote_post_id, status, video_uri, error, created_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(publish_id) DO UPDATE SET
                 remote_post_id=excluded.remote_post_id, status=excluded.status,
                 error=excluded.error""",
            (publish_id, project_id, platform, remote_post_id, status,
             video_uri, error, _utcnow()),
        )
        self.db.commit()

    def get(self, publish_id: str) -> Optional[Dict[str, Any]]:
        row = self.db.execute(
            "SELECT * FROM publish_jobs WHERE publish_id=?", (publish_id,)
        ).fetchone()
        return dict(row) if row else None
