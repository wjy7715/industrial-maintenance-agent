from __future__ import annotations

from pathlib import Path

from ..domain import DiagnosisRequest, Evidence, MaintenancePlan, ToolTrace
from ..repositories import EquipmentRepository, KnowledgeRepository, SessionRepository
from ..safety import SafetyPolicy
from ..tools import (
    FaultHistoryTool,
    KnowledgeSearchTool,
    RiskAssessmentTool,
    TelemetryTool,
    ToolResult,
    execute_tool,
)


class MaintenanceOrchestrator:
    def __init__(
        self,
        telemetry: TelemetryTool,
        history: FaultHistoryTool,
        knowledge: KnowledgeSearchTool,
        risk: RiskAssessmentTool,
        safety: SafetyPolicy | None = None,
        sessions: SessionRepository | None = None,
    ) -> None:
        self.telemetry = telemetry
        self.history = history
        self.knowledge = knowledge
        self.risk = risk
        self.safety = safety or SafetyPolicy()
        self.sessions = sessions

    @classmethod
    def from_project(cls, root: Path) -> "MaintenanceOrchestrator":
        equipment = EquipmentRepository(root / "data" / "sample" / "equipment.json")
        knowledge = KnowledgeRepository(root / "data" / "knowledge" / "pump_troubleshooting.json")
        return cls(
            TelemetryTool(equipment), FaultHistoryTool(equipment),
            KnowledgeSearchTool(knowledge), RiskAssessmentTool(),
            sessions=SessionRepository(root / "data" / "runtime" / "assistant.db"),
        )

    def diagnose(self, request: DiagnosisRequest) -> MaintenancePlan:
        telemetry_result = execute_tool(self.telemetry, request.equipment_id)
        if telemetry_result.status == "failed":
            raise LookupError(telemetry_result.error or f"未找到设备：{request.equipment_id}")
        telemetry = telemetry_result.data
        plan = MaintenancePlan(
            equipment_id=request.equipment_id,
            equipment_type=telemetry["equipment_type"],
            request_id=request.request_id,
        )
        plan.tool_trace.append(_trace(telemetry_result, f"读取 {len(telemetry['values'])} 个遥测字段"))
        plan.facts.append(
            f"设备 {request.equipment_id}（{telemetry.get('equipment_model') or '型号未提供'}）"
        )
        plan.facts.extend(f"{key}={value}" for key, value in telemetry["values"].items())
        plan.evidence.append(Evidence(
            "telemetry",
            telemetry["captured_at"] + "：" + "，".join(f"{k}={v}" for k, v in telemetry["values"].items()),
            "项目仿真设备数据（非真实现场）",
        ))

        if telemetry_result.quality == "stale":
            plan.unknowns.append("遥测已过期，无法代表设备当前实时状态。")

        if _needs_clarification(request):
            plan.status = "awaiting_clarification"
            plan.clarification_questions = [
                "具体观察到了什么现象（振动、温度、压力、流量、泄漏或声音）？",
                "现象从何时开始，是否持续或快速恶化？",
                "发生前是否有启停、维护、介质或工况变化？",
            ]
            plan.limitations.append("现象描述不足，系统尚未生成故障原因或维修动作。")
            plan.safety_warnings = self.safety.apply([], "unknown")
            self._record_session(request, plan)
            return plan

        history_result = execute_tool(self.history, request.equipment_id)
        plan.tool_trace.append(_trace(history_result, _history_summary(history_result)))
        history = history_result.data or {"active_errors": [], "maintenance_history": []}
        if history_result.status == "failed":
            plan.unknowns.append("故障历史查询失败，本草稿未使用历史记录。")
        elif history_result.status == "empty":
            plan.unknowns.append("未找到活动错误或维修历史；这不代表设备从未故障。")
        if history["active_errors"]:
            plan.facts.append("活动错误：" + "、".join(history["active_errors"]))
            plan.evidence.append(Evidence(
                "fault_history", "当前错误：" + "、".join(history["active_errors"]),
                "项目仿真故障记录（非真实现场）",
            ))
        if history["maintenance_history"]:
            plan.evidence.append(Evidence(
                "maintenance_history",
                "；".join(
                    f"{item.get('date', '日期未知')} {item.get('action', '动作未知')}"
                    for item in history["maintenance_history"]
                ),
                "项目仿真维修历史（非真实现场）",
            ))

        risk_result = execute_tool(self.risk, telemetry["equipment_type"], telemetry["values"])
        plan.tool_trace.append(_trace(risk_result, _risk_summary(risk_result)))
        risk = risk_result.data or {"level": "unknown", "signals": []}
        plan.risk_level = risk["level"]
        if risk_result.status == "failed" or risk["level"] == "unknown":
            plan.unknowns.append("没有可用的适用风险规则，风险等级保持未知。")
        if risk["signals"]:
            plan.facts.extend(risk["signals"])
            plan.evidence.append(Evidence(
                "risk_rule", "；".join(risk["signals"]), "项目演示阈值规则",
                source_version=self.risk.version,
            ))
        plan.conflicts.extend(_detect_conflicts(telemetry["values"], history["active_errors"]))

        knowledge_result = execute_tool(
            self.knowledge,
            telemetry["equipment_type"],
            request.symptoms,
            telemetry.get("equipment_model"),
        )
        matches = knowledge_result.data or []
        plan.tool_trace.append(_trace(knowledge_result, _knowledge_summary(knowledge_result)))
        if knowledge_result.status == "failed":
            plan.unknowns.append("维修知识检索失败，未生成具体维修动作。")
        elif knowledge_result.status == "empty":
            plan.unknowns.append("没有找到适用于当前设备型号和现象的已发布知识。")

        warnings: list[str] = []
        for entry in matches:
            plan.candidate_causes.extend(entry["possible_causes"])
            plan.inspection_steps.extend(entry["inspection_steps"])
            plan.corrective_actions.extend(entry["corrective_actions"])
            warnings.extend(entry.get("safety_warnings", []))
            source = entry["source"]
            plan.evidence.append(Evidence(
                "maintenance_knowledge", entry["summary"], source["name"],
                source["url"], source["location"], entry["knowledge_version"],
                entry["knowledge_id"],
            ))

        plan.candidate_causes = _unique(plan.candidate_causes)
        plan.inspection_steps = _unique(plan.inspection_steps)
        plan.corrective_actions = _unique(plan.corrective_actions)
        if plan.risk_level == "critical":
            plan.corrective_actions = []
            plan.limitations.append("风险达到严重等级，系统已隐藏具体纠正动作；请按现场应急规程升级处理。")
        plan.safety_warnings = self.safety.apply(warnings, plan.risk_level)
        plan.limitations.append("运行数据与维修知识来自不同公开/仿真来源，未声称属于同一真实设备。")
        if not matches:
            plan.limitations.append("知识库没有可靠匹配，系统没有生成猜测性维修措施。")
        self._record_session(request, plan)
        return plan

    def _record_session(self, request: DiagnosisRequest, plan: MaintenancePlan) -> None:
        if self.sessions is None:
            return
        try:
            self.sessions.record_session(request, plan)
        except Exception as exc:
            plan.tool_trace.append(ToolTrace(
                "record_audit", "failed", "审计记录写入失败", error=f"{type(exc).__name__}: {exc}"
            ))
            plan.limitations.append("审计记录写入失败；本次结果不可作为已留痕会话使用。")


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _trace(result: ToolResult, summary: str) -> ToolTrace:
    return ToolTrace(
        result.tool_name,
        result.status,
        summary,
        result.tool_version,
        result.started_at,
        result.finished_at,
        result.duration_ms,
        result.error,
    )


def _history_summary(result: ToolResult) -> str:
    if result.status == "failed":
        return "故障历史查询失败"
    data = result.data or {}
    return f"读取 {len(data.get('active_errors', []))} 个当前错误、{len(data.get('maintenance_history', []))} 条维修历史"


def _risk_summary(result: ToolResult) -> str:
    if result.status == "failed":
        return "风险规则执行失败"
    return f"风险等级 {(result.data or {}).get('level', 'unknown')}"


def _knowledge_summary(result: ToolResult) -> str:
    if result.status == "failed":
        return "维修知识检索失败"
    return f"命中 {len(result.data or [])} 条可追溯知识"


def _needs_clarification(request: DiagnosisRequest) -> bool:
    normalized = "".join(request.symptoms).strip().casefold()
    return normalized in {"异常", "故障", "有问题", "不正常", "坏了"}


def _detect_conflicts(telemetry: dict[str, object], active_errors: list[str]) -> list[str]:
    conflicts: list[str] = []
    vibration = telemetry.get("vibration_mm_s")
    if "VIBRATION_HIGH" in active_errors and isinstance(vibration, (int, float)) and vibration < 4.5:
        conflicts.append("活动告警显示振动过高，但当前振动值低于演示告警阈值，请核对时间与传感器。")
    temperature = telemetry.get("temperature_c")
    if (
        "BEARING_TEMPERATURE_HIGH" in active_errors
        and isinstance(temperature, (int, float))
        and temperature < 65.0
    ):
        conflicts.append("活动告警显示轴承温度过高，但当前温度低于演示告警阈值，请核对时间与传感器。")
    return conflicts
