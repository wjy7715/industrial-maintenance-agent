from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..domain import DiagnosisRequest, MaintenancePlan


ALLOWED_RATINGS = {"effective", "partial", "ineffective", "dangerous"}


class SessionRepository:
    """Local audit and feedback store. It never grants tool authority."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS diagnosis_sessions (
                    session_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    equipment_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    rating TEXT NOT NULL,
                    comment TEXT NOT NULL DEFAULT '',
                    reviewer_role TEXT NOT NULL DEFAULT 'operator',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES diagnosis_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS expert_reviews (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    conclusion TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    reviewer_role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES diagnosis_sessions(session_id)
                );
                """
            )
            connection.commit()

    def record_session(self, request: DiagnosisRequest, plan: MaintenancePlan) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO diagnosis_sessions
                (session_id, request_id, equipment_id, created_at, request_json, plan_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.session_id,
                    request.request_id,
                    request.equipment_id,
                    plan.created_at,
                    json.dumps(asdict(request), ensure_ascii=False),
                    json.dumps(plan.to_dict(), ensure_ascii=False),
                ),
            )
            connection.commit()

    def add_feedback(
        self,
        session_id: str,
        rating: str,
        comment: str = "",
        reviewer_role: str = "operator",
    ) -> int:
        if rating not in ALLOWED_RATINGS:
            raise ValueError(f"不支持的反馈类型：{rating}")
        with closing(self._connect()) as connection:
            exists = connection.execute(
                "SELECT 1 FROM diagnosis_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if exists is None:
                raise LookupError(f"未找到诊断会话：{session_id}")
            cursor = connection.execute(
                """
                INSERT INTO feedback (session_id, rating, comment, reviewer_role, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    rating,
                    comment.strip(),
                    reviewer_role,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()
            feedback_id = int(cursor.lastrowid)
        return feedback_id

    def recent_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT session_id, request_id, equipment_id, created_at, plan_json
                FROM diagnosis_sessions ORDER BY created_at DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [
            {
                "session_id": row["session_id"],
                "request_id": row["request_id"],
                "equipment_id": row["equipment_id"],
                "created_at": row["created_at"],
                "plan": json.loads(row["plan_json"]),
            }
            for row in rows
        ]

    def feedback_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT feedback_id, rating, comment, reviewer_role, created_at
                FROM feedback WHERE session_id = ? ORDER BY feedback_id
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_expert_review(
        self,
        session_id: str,
        status: str,
        conclusion: str,
        reviewer_id: str,
        reviewer_role: str,
    ) -> int:
        with closing(self._connect()) as connection:
            exists = connection.execute(
                "SELECT 1 FROM diagnosis_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if exists is None:
                raise LookupError(f"未找到诊断会话：{session_id}")
            cursor = connection.execute(
                """
                INSERT INTO expert_reviews
                (session_id, status, conclusion, reviewer_id, reviewer_role, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, status, conclusion.strip(), reviewer_id, reviewer_role,
                 datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def expert_reviews_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT review_id, status, conclusion, reviewer_id, reviewer_role, created_at
                FROM expert_reviews WHERE session_id = ? ORDER BY review_id
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT session_id, request_id, equipment_id, created_at, request_json, plan_json
                FROM diagnosis_sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "session_id": row["session_id"],
            "request_id": row["request_id"],
            "equipment_id": row["equipment_id"],
            "created_at": row["created_at"],
            "request": json.loads(row["request_json"]),
            "plan": json.loads(row["plan_json"]),
            "feedback": self.feedback_for_session(session_id),
            "expert_reviews": self.expert_reviews_for_session(session_id),
        }
