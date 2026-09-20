"""SQLite storage for CineAgent v4. WAL + foreign keys; single source of truth."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


class Database:
    """Thin wrapper around a SQLite connection with WAL enabled."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn = conn
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, seq: list[tuple]) -> None:
        self.conn.executemany(sql, seq)
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    def transaction(self):
        """Context manager for an atomic transaction (SQLite autocommit-style)."""
        return self.conn  # SQLite: use explicit BEGIN/COMMIT via python sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_id   TEXT PRIMARY KEY,
    topic        TEXT NOT NULL,
    objective    TEXT,
    audience     TEXT,
    platform     TEXT,
    language     TEXT,
    target_duration REAL,
    aspect_ratio TEXT,
    quality_mode TEXT,
    budget_limit REAL,
    status       TEXT,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS scenes (
    scene_id   TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    scene_index INTEGER,
    title      TEXT,
    goal       TEXT,
    story_beat TEXT,
    narration  TEXT,
    emotion    TEXT,
    start_time REAL,
    end_time   REAL
);

CREATE TABLE IF NOT EXISTS shots (
    shot_id      TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,
    scene_id     TEXT NOT NULL,
    start_time   REAL,
    end_time     REAL,
    duration     REAL,
    narration_segment TEXT,
    subject      TEXT,
    action       TEXT,
    shot_size    TEXT,
    camera_angle TEXT,
    camera_motion TEXT,
    generation_strategy TEXT,
    quality_tier TEXT,
    state        TEXT,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id   TEXT PRIMARY KEY,
    project_id TEXT,
    source     TEXT,
    type       TEXT,
    uri        TEXT,
    tags       TEXT,
    license_note TEXT,
    provenance TEXT,
    hash       TEXT,
    reuse_count INTEGER,
    meta       TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    project_id  TEXT,
    scene_id    TEXT,
    shot_id     TEXT,
    provider    TEXT,
    model       TEXT,
    operation   TEXT,
    remote_job_id TEXT,
    state       TEXT,
    submitted_at TEXT,
    completed_at TEXT,
    retry_count INTEGER,
    input_asset_ids TEXT,
    output_asset_ids TEXT,
    estimated_cost REAL,
    actual_cost  REAL,
    error       TEXT,
    payload     TEXT
);

CREATE TABLE IF NOT EXISTS usage_events (
    event_id    TEXT PRIMARY KEY,
    project_id  TEXT,
    scene_id    TEXT,
    shot_id     TEXT,
    provider    TEXT,
    model       TEXT,
    operation   TEXT,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    image_count INTEGER,
    video_seconds REAL,
    audio_seconds REAL,
    retry       INTEGER,
    estimated_cost REAL,
    actual_cost  REAL,
    status      TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS qa_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shot_id     TEXT,
    project_id  TEXT,
    stage       TEXT,
    score       REAL,
    threshold   REAL,
    decision    TEXT,
    problems    TEXT,
    severities  TEXT,
    repair_instructions TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS publish_jobs (
    publish_id  TEXT PRIMARY KEY,
    project_id  TEXT,
    platform    TEXT,
    remote_post_id TEXT,
    status      TEXT,
    video_uri   TEXT,
    error       TEXT,
    created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_shots_project ON shots(project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_usage_project ON usage_events(project_id);
"""
