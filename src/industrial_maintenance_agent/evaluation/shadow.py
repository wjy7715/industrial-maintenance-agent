from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from ..repositories import SessionRepository


@dataclass(frozen=True)
class ShadowEvaluationReport:
    generated_at: str
    total_sessions: int
    reviewed_sessions: int
    critical_sessions: int
    tool_calls: int
    tool_success_rate: float
    evidence_coverage_rate: float
    dangerous_feedback_count: int
    dangerous_feedback_rate: float
    critical_action_violation_count: int
    scope_notice: str = "仅基于本地审计会话，不代表真实工厂效果或工业诊断准确率。"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_shadow_report(
    sessions: SessionRepository,
    limit: int = 100,
) -> ShadowEvaluationReport:
    records = sessions.recent_sessions(limit=limit)
    tool_calls = 0
    successful_tools = 0
    actionable_sessions = 0
    cited_actionable_sessions = 0
    critical_sessions = 0
    critical_action_violations = 0
    reviewed_sessions = 0
    dangerous_feedback_count = 0

    for record in records:
        plan = record["plan"]
        traces = plan.get("tool_trace", [])
        tool_calls += len(traces)
        successful_tools += sum(
            1 for trace in traces if trace.get("status") in {"success", "empty"}
        )

        actions = plan.get("corrective_actions", [])
        if actions:
            actionable_sessions += 1
            has_citation = any(
                evidence.get("kind") == "maintenance_knowledge"
                and evidence.get("source_name")
                for evidence in plan.get("evidence", [])
            )
            cited_actionable_sessions += int(has_citation)

        if plan.get("risk_level") == "critical":
            critical_sessions += 1
            critical_action_violations += int(bool(actions))

        detail = sessions.get_session(record["session_id"])
        feedback = detail["feedback"] if detail else []
        if feedback:
            reviewed_sessions += 1
        dangerous_feedback_count += sum(1 for item in feedback if item["rating"] == "dangerous")

    return ShadowEvaluationReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_sessions=len(records),
        reviewed_sessions=reviewed_sessions,
        critical_sessions=critical_sessions,
        tool_calls=tool_calls,
        tool_success_rate=_ratio(successful_tools, tool_calls),
        evidence_coverage_rate=_ratio(cited_actionable_sessions, actionable_sessions),
        dangerous_feedback_count=dangerous_feedback_count,
        dangerous_feedback_rate=_ratio(dangerous_feedback_count, reviewed_sessions),
        critical_action_violation_count=critical_action_violations,
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0
