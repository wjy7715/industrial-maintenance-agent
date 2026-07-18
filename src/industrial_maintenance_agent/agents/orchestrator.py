from __future__ import annotations

from pathlib import Path

from ..domain import DiagnosisRequest, Evidence, MaintenancePlan, ToolTrace
from ..repositories import EquipmentRepository, KnowledgeRepository
from ..safety import SafetyPolicy
from ..tools import FaultHistoryTool, KnowledgeSearchTool, RiskAssessmentTool, TelemetryTool


class MaintenanceOrchestrator:
    def __init__(
        self,
        telemetry: TelemetryTool,
        history: FaultHistoryTool,
        knowledge: KnowledgeSearchTool,
        risk: RiskAssessmentTool,
        safety: SafetyPolicy | None = None,
    ) -> None:
        self.telemetry = telemetry
        self.history = history
        self.knowledge = knowledge
        self.risk = risk
        self.safety = safety or SafetyPolicy()

    @classmethod
    def from_project(cls, root: Path) -> "MaintenanceOrchestrator":
        equipment = EquipmentRepository(root / "data" / "sample" / "equipment.json")
        knowledge = KnowledgeRepository(root / "data" / "knowledge" / "pump_troubleshooting.json")
        return cls(
            TelemetryTool(equipment), FaultHistoryTool(equipment),
            KnowledgeSearchTool(knowledge), RiskAssessmentTool(),
        )

    def diagnose(self, request: DiagnosisRequest) -> MaintenancePlan:
        telemetry = self.telemetry.run(request.equipment_id)
        history = self.history.run(request.equipment_id)
        risk = self.risk.run(telemetry["equipment_type"], telemetry["values"])
        matches = self.knowledge.run(telemetry["equipment_type"], request.symptoms)

        plan = MaintenancePlan(
            equipment_id=request.equipment_id,
            equipment_type=telemetry["equipment_type"],
            risk_level=risk["level"],
        )
        plan.tool_trace.extend([
            ToolTrace(self.telemetry.name, "success", f"读取 {len(telemetry['values'])} 个遥测字段"),
            ToolTrace(self.history.name, "success", f"读取 {len(history['active_errors'])} 个当前错误"),
            ToolTrace(self.risk.name, "success", f"风险等级 {risk['level']}"),
            ToolTrace(self.knowledge.name, "success", f"命中 {len(matches)} 条可追溯知识"),
        ])
        plan.evidence.append(Evidence(
            "telemetry",
            telemetry["captured_at"] + "：" + "，".join(f"{k}={v}" for k, v in telemetry["values"].items()),
            "项目仿真设备数据（非真实现场）",
        ))
        if history["active_errors"]:
            plan.evidence.append(Evidence(
                "fault_history", "当前错误：" + "、".join(history["active_errors"]),
                "项目仿真故障记录（非真实现场）",
            ))
        if risk["signals"]:
            plan.evidence.append(Evidence(
                "risk_rule", "；".join(risk["signals"]), "项目演示阈值规则",
            ))

        warnings: list[str] = []
        for entry in matches:
            plan.candidate_causes.extend(entry["possible_causes"])
            plan.inspection_steps.extend(entry["inspection_steps"])
            plan.corrective_actions.extend(entry["corrective_actions"])
            warnings.extend(entry.get("safety_warnings", []))
            source = entry["source"]
            plan.evidence.append(Evidence(
                "maintenance_knowledge", entry["summary"], source["name"],
                source["url"], source["location"],
            ))

        plan.candidate_causes = _unique(plan.candidate_causes)
        plan.inspection_steps = _unique(plan.inspection_steps)
        plan.corrective_actions = _unique(plan.corrective_actions)
        plan.safety_warnings = self.safety.apply(warnings, plan.risk_level)
        plan.limitations.append("运行数据与维修知识来自不同公开/仿真来源，未声称属于同一真实设备。")
        if not matches:
            plan.limitations.append("知识库没有可靠匹配，系统没有生成猜测性维修措施。")
        return plan


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
