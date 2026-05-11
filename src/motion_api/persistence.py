from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class StoredTemplate:
    template_id: str
    name: str
    mode: str
    video_uri: str
    notes: str | None
    trim_start_sec: float | None = None
    trim_end_sec: float | None = None


@dataclass(slots=True)
class AnalysisVideoRecord:
    id: int
    session_id: str
    step_index: int
    set_index: int
    exercise_name: str
    source_video_uri: str
    comparison_video_uri: str
    similarity: float
    normalized_distance: float
    created_at: str


class SqliteStore:
    """SQLite persistence for templates, workout sessions, and final analysis results."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._event_queue: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=50000)
        self._event_stop = threading.Event()
        self._event_worker: threading.Thread | None = None
        self._event_worker_started = False
        self._worker_batch_size = 256
        self._dropped_event_rows = 0

    def initialize(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS templates (
                    template_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    video_uri TEXT NOT NULL,
                    notes TEXT,
                    trim_start_sec REAL,
                    trim_end_sec REAL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS template_profiles (
                    template_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    samples INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(template_id) REFERENCES templates(template_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS workout_sessions (
                    session_id TEXT PRIMARY KEY,
                    speak_enabled INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    plan_json TEXT NOT NULL,
                    latest_phase TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS workout_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES workout_sessions(session_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS workout_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    set_index INTEGER NOT NULL,
                    video_uri TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    observed_rep_count INTEGER,
                    segment_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES workout_sessions(session_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS workout_results (
                    session_id TEXT PRIMARY KEY,
                    done INTEGER NOT NULL,
                    total_events INTEGER NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES workout_sessions(session_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS analysis_videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    set_index INTEGER NOT NULL,
                    exercise_name TEXT NOT NULL,
                    source_video_uri TEXT NOT NULL,
                    comparison_video_uri TEXT NOT NULL,
                    similarity REAL NOT NULL,
                    normalized_distance REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(session_id, step_index, set_index, comparison_video_uri)
                );
                """
            )
            self._ensure_templates_columns()
            self._conn.commit()
        self._start_event_worker()

    def _ensure_templates_columns(self) -> None:
        cols = {
            str(row["name"]): str(row["type"])
            for row in self._conn.execute("PRAGMA table_info(templates)").fetchall()
        }
        if "trim_start_sec" not in cols:
            self._conn.execute("ALTER TABLE templates ADD COLUMN trim_start_sec REAL")
        if "trim_end_sec" not in cols:
            self._conn.execute("ALTER TABLE templates ADD COLUMN trim_end_sec REAL")

    def _start_event_worker(self) -> None:
        if self._event_worker_started:
            return
        self._event_worker_started = True
        self._event_worker = threading.Thread(target=self._event_worker_loop, name="sqlite-event-writer", daemon=True)
        self._event_worker.start()

    def _event_worker_loop(self) -> None:
        while not self._event_stop.is_set() or not self._event_queue.empty():
            rows = self._drain_event_rows(timeout=0.2, max_rows=self._worker_batch_size)
            if not rows:
                continue
            with self._lock:
                self._conn.executemany(
                    "INSERT INTO workout_events(session_id, event_json) VALUES(?, ?)",
                    rows,
                )
                self._conn.commit()

    def _drain_event_rows(self, *, timeout: float, max_rows: int) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        try:
            rows.append(self._event_queue.get(timeout=timeout))
        except queue.Empty:
            return rows

        while len(rows) < max_rows:
            try:
                rows.append(self._event_queue.get_nowait())
            except queue.Empty:
                break
        return rows

    def _enqueue_event_rows(self, rows: list[tuple[str, str]]) -> int:
        accepted = 0
        for row in rows:
            try:
                self._event_queue.put_nowait(row)
                accepted += 1
            except queue.Full:
                self._dropped_event_rows += 1
        return accepted

    def flush_event_writer(self, timeout_seconds: float = 2.0) -> bool:
        deadline = time.time() + max(0.0, timeout_seconds)
        while time.time() < deadline:
            if self._event_queue.empty():
                return True
            time.sleep(0.01)
        return self._event_queue.empty()

    def close(self, timeout_seconds: float = 2.0) -> None:
        self.flush_event_writer(timeout_seconds=timeout_seconds)
        self._event_stop.set()
        worker = self._event_worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=max(0.1, timeout_seconds))
        with self._lock:
            self._conn.close()

    def queue_stats(self) -> dict[str, int]:
        return {
            "pending": int(self._event_queue.qsize()),
            "dropped": int(self._dropped_event_rows),
        }

    def upsert_template(self, template: StoredTemplate) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO templates(template_id, name, mode, video_uri, notes, trim_start_sec, trim_end_sec)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                    name=excluded.name,
                    mode=excluded.mode,
                    video_uri=excluded.video_uri,
                    notes=excluded.notes,
                    trim_start_sec=excluded.trim_start_sec,
                    trim_end_sec=excluded.trim_end_sec,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    template.template_id,
                    template.name,
                    template.mode,
                    template.video_uri,
                    template.notes,
                    template.trim_start_sec,
                    template.trim_end_sec,
                ),
            )
            self._conn.commit()

    def list_templates(self) -> list[StoredTemplate]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT template_id, name, mode, video_uri, notes, trim_start_sec, trim_end_sec
                FROM templates
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [
            StoredTemplate(
                template_id=str(r["template_id"]),
                name=str(r["name"]),
                mode=str(r["mode"]),
                video_uri=str(r["video_uri"]),
                notes=(str(r["notes"]) if r["notes"] is not None else None),
                trim_start_sec=(float(r["trim_start_sec"]) if r["trim_start_sec"] is not None else None),
                trim_end_sec=(float(r["trim_end_sec"]) if r["trim_end_sec"] is not None else None),
            )
            for r in rows
        ]

    def delete_template(self, template_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM templates WHERE template_id = ?", (template_id,))
            self._conn.commit()

    def upsert_template_profile(self, template_id: str, profile: dict[str, Any]) -> None:
        samples = int(profile.get("samples", 0) or 0)
        payload = json.dumps(profile, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO template_profiles(template_id, profile_json, samples)
                VALUES(?, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                    profile_json=excluded.profile_json,
                    samples=excluded.samples,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (template_id, payload, samples),
            )
            self._conn.commit()

    def get_template_profile(self, template_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT profile_json FROM template_profiles WHERE template_id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["profile_json"]))

    def delete_template_profile(self, template_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM template_profiles WHERE template_id = ?", (template_id,))
            self._conn.commit()

    def list_template_profiles(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT template_id, profile_json FROM template_profiles").fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            out[str(row["template_id"])] = json.loads(str(row["profile_json"]))
        return out

    def create_workout_session(self, session_id: str, *, speak_enabled: bool, plan: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO workout_sessions(session_id, speak_enabled, status, done, plan_json)
                VALUES(?, ?, 'active', 0, ?)
                """,
                (session_id, int(speak_enabled), json.dumps(plan, ensure_ascii=False)),
            )
            self._conn.commit()

    def update_workout_session_state(self, session_id: str, *, latest_phase: str, done: bool, status: str = "active") -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE workout_sessions
                SET latest_phase = ?, done = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (latest_phase, int(done), status, session_id),
            )
            self._conn.commit()

    def append_workout_event(self, session_id: str, event: dict[str, Any]) -> None:
        self._enqueue_event_rows([(session_id, json.dumps(event, ensure_ascii=False))])

    def append_workout_events_batch(self, session_id: str, events: list[dict[str, Any]]) -> int:
        if not events:
            return 0
        rows = [(session_id, json.dumps(event, ensure_ascii=False)) for event in events]
        return self._enqueue_event_rows(rows)

    def list_workout_events(self, session_id: str) -> list[dict[str, Any]]:
        self.flush_event_writer(timeout_seconds=3.0)
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_json FROM workout_events WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [json.loads(str(row["event_json"])) for row in rows]

    def append_segment(self, session_id: str, segment: dict[str, Any]) -> int:
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO workout_segments(
                    session_id, step_index, set_index, video_uri, duration_seconds, observed_rep_count, segment_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    int(segment.get("step_index", 0)),
                    int(segment.get("set_index", 0)),
                    str(segment.get("video_uri", "")),
                    float(segment.get("duration_seconds", 0.0)),
                    int(segment.get("observed_rep_count")) if segment.get("observed_rep_count") is not None else None,
                    json.dumps(segment, ensure_ascii=False),
                ),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def list_segments(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT segment_json FROM workout_segments WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [json.loads(str(row["segment_json"])) for row in rows]

    def save_workout_result(self, session_id: str, *, done: bool, total_events: int, analysis: dict[str, Any]) -> None:
        payload = json.dumps(analysis, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO workout_results(session_id, done, total_events, analysis_json)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    done=excluded.done,
                    total_events=excluded.total_events,
                    analysis_json=excluded.analysis_json,
                    created_at=CURRENT_TIMESTAMP
                """,
                (session_id, int(done), int(total_events), payload),
            )
            self._conn.commit()

    def get_workout_result(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT done, total_events, analysis_json FROM workout_results WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "done": bool(row["done"]),
            "total_events": int(row["total_events"]),
            "analysis": json.loads(str(row["analysis_json"])),
        }

    def upsert_analysis_video(
        self,
        *,
        session_id: str,
        step_index: int,
        set_index: int,
        exercise_name: str,
        source_video_uri: str,
        comparison_video_uri: str,
        similarity: float,
        normalized_distance: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO analysis_videos(
                    session_id, step_index, set_index, exercise_name,
                    source_video_uri, comparison_video_uri, similarity, normalized_distance
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, step_index, set_index, comparison_video_uri) DO UPDATE SET
                    exercise_name=excluded.exercise_name,
                    source_video_uri=excluded.source_video_uri,
                    similarity=excluded.similarity,
                    normalized_distance=excluded.normalized_distance
                """,
                (
                    session_id,
                    int(step_index),
                    int(set_index),
                    exercise_name,
                    source_video_uri,
                    comparison_video_uri,
                    float(similarity),
                    float(normalized_distance),
                ),
            )
            self._conn.commit()

    def list_analysis_videos(self) -> list[AnalysisVideoRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, session_id, step_index, set_index, exercise_name, source_video_uri,
                       comparison_video_uri, similarity, normalized_distance, created_at
                FROM analysis_videos
                ORDER BY id DESC
                """
            ).fetchall()
        return [
            AnalysisVideoRecord(
                id=int(row["id"]),
                session_id=str(row["session_id"]),
                step_index=int(row["step_index"]),
                set_index=int(row["set_index"]),
                exercise_name=str(row["exercise_name"]),
                source_video_uri=str(row["source_video_uri"]),
                comparison_video_uri=str(row["comparison_video_uri"]),
                similarity=float(row["similarity"]),
                normalized_distance=float(row["normalized_distance"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def get_analysis_video(self, video_id: int) -> AnalysisVideoRecord | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, session_id, step_index, set_index, exercise_name, source_video_uri,
                       comparison_video_uri, similarity, normalized_distance, created_at
                FROM analysis_videos
                WHERE id = ?
                """,
                (int(video_id),),
            ).fetchone()
        if row is None:
            return None
        return AnalysisVideoRecord(
            id=int(row["id"]),
            session_id=str(row["session_id"]),
            step_index=int(row["step_index"]),
            set_index=int(row["set_index"]),
            exercise_name=str(row["exercise_name"]),
            source_video_uri=str(row["source_video_uri"]),
            comparison_video_uri=str(row["comparison_video_uri"]),
            similarity=float(row["similarity"]),
            normalized_distance=float(row["normalized_distance"]),
            created_at=str(row["created_at"]),
        )

    def delete_analysis_video(self, video_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM analysis_videos WHERE id = ?", (int(video_id),))
            self._conn.commit()
            return cur.rowcount > 0
