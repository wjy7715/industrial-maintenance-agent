from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class DiagnosisRequest:
    equipment_id: str
    symptoms: tuple[str, ...]
    request_id: str = field(default_factory=lambda: str(uuid4()))
    observed_at: str | None = None
    context: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.equipment_id.strip():
            raise ValueError("equipment_id 不能为空")
        if not any(item.strip() for item in self.symptoms):
            raise ValueError("至少需要一个故障现象")


@dataclass(frozen=True)
class Evidence:
    kind: str
    summary: str
    source_name: str
    source_url: str | None = None
    source_location: str | None = None
    source_version: str | None = None
    knowledge_id: str | None = None


@dataclass(frozen=True)
class ToolTrace:
    tool: str
    status: str
    summary: str
    version: str = "1.0"
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class MaintenancePlan:
    equipment_id: str
    equipment_type: str
    request_id: str = ""
    session_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "draft"
    risk_level: str = "unknown"
    facts: list[str] = field(default_factory=list)
    candidate_causes: list[str] = field(default_factory=list)
    inspection_steps: list[str] = field(default_factory=list)
    corrective_actions: list[str] = field(default_factory=list)
    safety_warnings: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    tool_trace: list[ToolTrace] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    requires_human_confirmation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
