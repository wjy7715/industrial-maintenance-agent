from __future__ import annotations

from ..domain import AccessContext
from ..repositories.sessions import SessionRepository
from ..safety import AccessPolicy


class ExpertReviewService:
    allowed_statuses = {"approved", "needs_revision", "rejected", "unsafe"}

    def __init__(self, sessions: SessionRepository, access_policy: AccessPolicy | None = None) -> None:
        self.sessions = sessions
        self.access_policy = access_policy or AccessPolicy()

    def submit(
        self, access: AccessContext, session_id: str, status: str, conclusion: str
    ) -> int:
        if status not in self.allowed_statuses:
            raise ValueError(f"不支持的专家审核状态：{status}")
        if not conclusion.strip():
            raise ValueError("专家审核结论不能为空")
        detail = self.sessions.get_session(session_id)
        if detail is None:
            raise LookupError(f"未找到诊断会话：{session_id}")
        self.access_policy.authorize(access, "review", detail["plan"].get("site_id"))
        return self.sessions.add_expert_review(
            session_id, status, conclusion, access.actor_id, access.role
        )
