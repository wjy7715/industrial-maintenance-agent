from __future__ import annotations

from pathlib import Path

from ..domain import AccessContext, DiagnosisRequest, Evidence, MaintenancePlan, ToolTrace
from ..repositories import (
    EquipmentDataSource,
    EquipmentRepository,
    HistoryDataSource,
    KnowledgeRepository,
    SessionRepository,
)
from ..safety import (
    MaintenancePlanValidator,
    AccessPolicy,
    PlanValidationReport,
    SafetyPolicy,
    ToolPermissionRegistry,
)
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
        permissions: ToolPermissionRegistry | None = None,
        validator: MaintenancePlanValidator | None = None,
        sessions: SessionRepository | None = None,
        access_policy: AccessPolicy | None = None,
    ) -> None:
        self.telemetry = telemetry
        self.history = history
        self.knowledge = knowledge
        self.risk = risk
        self.safety = safety or SafetyPolicy()
        self.permissions = permissions or ToolPermissionRegistry()
        self.validator = validator or MaintenancePlanValidator()
        self.sessions = sessions
        self.access_policy = access_policy or AccessPolicy()

    @classmethod
    def from_project(
        cls,
        root: Path,
        equipment: EquipmentDataSource | None = None,
        history: HistoryDataSource | None = None,
    ) -> "MaintenanceOrchestrator":
        if equipment is None:
            equipment = EquipmentRepository(root / "data" / "sample" / "equipment.json")
        if history is None:
            history = equipment
        knowledge = KnowledgeRepository(root / "data" / "knowledge" / "pump_troubleshooting.json")
        return cls(
            TelemetryTool(equipment), FaultHistoryTool(history),
            KnowledgeSearchTool(knowledge), RiskAssessmentTool(),
            sessions=SessionRepository(root / "data" / "runtime" / "assistant.db"),
        )

    def diagnose(
        self,
        request: DiagnosisRequest,
        access: AccessContext | None = None,
    ) -> MaintenancePlan:
        access = access or AccessContext.local_technician()
        site_id = self.telemetry.repository.get_scope(request.equipment_id)
        if site_id is None:
            raise LookupError("未找到设备或无权访问")
        try:
            self.access_policy.authorize(access, "diagnose", site_id)
        except PermissionError as exc:
            raise LookupError("未找到设备或无权访问") from exc
        telemetry_result = execute_tool(
            self.telemetry,
            request.equipment_id,
            permission_registry=self.permissions,
        )
        if telemetry_result.status == "failed":
            raise LookupError(telemetry_result.error or f"未找到设备：{request.equipment_id}")
        telemetry = telemetry_result.data
        plan = MaintenancePlan(
            equipment_id=request.equipment_id,
            equipment_type=telemetry["equipment_type"],
            request_id=request.request_id,
            site_id=site_id,
            actor_id=access.actor_id,
            actor_role=access.role,
            identity_source=access.identity_source,
        )
        plan.tool_trace.append(_trace(telemetry_result, f"读取 {len(telemetry['values'])} 个遥测字段"))
        telemetry_source = _source_label(telemetry_result, "未命名遥测数据源")
        plan.facts.append(
            f"设备 {request.equipment_id}（{telemetry.get('equipment_model') or '型号未提供'}）"
        )
        plan.facts.append(f"遥测数据源：{telemetry_source}")
        plan.facts.append(
            f"访问身份：{access.actor_id}（{access.role}，{access.identity_source}）｜站点：{site_id}"
        )
        plan.facts.extend(
            f"{key}={value} {telemetry['units'][key]}"
            for key, value in telemetry["values"].items()
        )
        plan.evidence.append(Evidence(
            "telemetry",
            telemetry["captured_at"] + "：" + "，".join(
                f"{key}={value} {telemetry['units'][key]}"
                for key, value in telemetry["values"].items()
            ),
            telemetry_source,
        ))

        if telemetry_result.quality == "stale":
            plan.unknowns.append("遥测已过期，无法代表设备当前实时状态。")
        elif telemetry_result.quality == "suspicious":
            plan.unknowns.append("遥测时间戳晚于系统时间，请先核对设备时钟和时区。")

        if _needs_clarification(request):
            plan.status = "awaiting_clarification"
            plan.clarification_questions = [
                "具体观察到了什么现象（振动、温度、压力、流量、泄漏或声音）？",
                "现象从何时开始，是否持续或快速恶化？",
                "发生前是否有启停、维护、介质或工况变化？",
            ]
            plan.limitations.append("现象描述不足，系统尚未生成故障原因或维修动作。")
            plan.safety_warnings = self.safety.apply([], "unknown")
            return self._finalize(request, plan)

        history_result = execute_tool(
            self.history,
            request.equipment_id,
            permission_registry=self.permissions,
        )
        plan.tool_trace.append(_trace(history_result, _history_summary(history_result)))
        history = history_result.data or {"active_errors": [], "maintenance_history": []}
        if history_result.status == "failed":
            plan.unknowns.append("故障历史查询失败，本草稿未使用历史记录。")
        elif history_result.status == "empty":
            plan.unknowns.append("未找到活动错误或维修历史；这不代表设备从未故障。")
        else:
            plan.facts.append(
                "故障/维修数据源：" + _source_label(history_result, "未命名故障历史数据源")
            )
        if history["active_errors"]:
            plan.facts.append("活动错误：" + "、".join(history["active_errors"]))
            plan.evidence.append(Evidence(
                "fault_history", "当前错误：" + "、".join(history["active_errors"]),
                _source_label(history_result, "未命名故障数据源"),
            ))
        if history["maintenance_history"]:
            plan.evidence.append(Evidence(
                "maintenance_history",
                "；".join(_maintenance_summary(item) for item in history["maintenance_history"]),
                _source_label(history_result, "未命名维修历史数据源"),
            ))

        risk_result = execute_tool(
            self.risk,
            telemetry["equipment_type"],
            telemetry["values"],
            telemetry["units"],
            permission_registry=self.permissions,
        )
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
            permission_registry=self.permissions,
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
        source_kind = telemetry_result.source.get("kind", "unknown")
        if source_kind == "synthetic_demo":
            plan.limitations.append("运行数据来自项目仿真设备，不代表真实工业现场。")
        elif source_kind == "user_imported_read_only":
            plan.limitations.append("运行数据来自用户导入的只读快照，系统未独立核验其现场真实性。")
        else:
            plan.limitations.append("运行数据源身份未完全验证，不应直接用于现场操作。")
        if history_result.source.get("kind") == "user_imported_history_read_only":
            plan.limitations.append("故障与维修闭环来自用户导入的只读记录，系统未独立核验。")
        plan.limitations.append("运行数据与维修知识来源彼此独立，未声称属于同一设备或厂商手册。")
        if not matches:
            plan.limitations.append("知识库没有可靠匹配，系统没有生成猜测性维修措施。")
        return self._finalize(request, plan)

    def _finalize(self, request: DiagnosisRequest, plan: MaintenancePlan) -> MaintenancePlan:
        try:
            report = self.validator.validate(plan)
        except Exception as exc:
            report = PlanValidationReport(
                False,
                (f"输出验证器异常：{type(exc).__name__}: {exc}",),
            )
        plan.validation_status = "passed" if report.valid else "blocked"
        plan.validation_errors = list(report.errors)
        plan.tool_trace.append(ToolTrace(
            "validate_output",
            "success" if report.valid else "failed",
            "输出安全验证通过" if report.valid else f"输出安全验证阻断 {len(report.errors)} 项",
            version=str(getattr(self.validator, "version", "unknown")),
            error="；".join(report.errors) or None,
        ))
        if not report.valid:
            plan.status = "blocked"
            plan.requires_human_confirmation = True
            plan.corrective_actions = []
            plan.limitations.append("输出安全验证未通过，系统已阻断具体维修动作。")
            plan.safety_warnings = self.safety.apply(
                ["请由现场专业人员复核验证错误后重新生成方案。"],
                plan.risk_level,
            )
        plan.limitations.extend(item for item in report.warnings if item not in plan.limitations)
        self._record_session(request, plan)
        return plan

    def _record_session(self, request: DiagnosisRequest, plan: MaintenancePlan) -> None:
        if self.sessions is None:
            return
        try:
            self.permissions.authorize("record_audit")
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


def _source_label(result: ToolResult, fallback: str) -> str:
    name = result.source.get("name") if result.source else None
    kind = result.source.get("kind") if result.source else None
    return f"{name or fallback}（{kind or 'unknown'}）"


def _history_summary(result: ToolResult) -> str:
    if result.status == "failed":
        return "故障历史查询失败"
    data = result.data or {}
    return f"读取 {len(data.get('active_errors', []))} 个当前错误、{len(data.get('maintenance_history', []))} 条维修历史"


def _maintenance_summary(item: dict[str, object]) -> str:
    parts = [
        str(item.get("date") or "日期未知"),
        str(item.get("action") or "动作未知"),
        "结果=" + str(item.get("result") or "未记录"),
    ]
    if item.get("confirmed_cause"):
        parts.append("确认原因=" + str(item["confirmed_cause"]))
    if item.get("verified_at"):
        parts.append("验证时间=" + str(item["verified_at"]))
    return " ".join(parts)


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
