from __future__ import annotations

from dataclasses import dataclass

from ..domain import MaintenancePlan


ALLOWED_STATUSES = {"draft", "awaiting_clarification", "blocked"}
ALLOWED_RISK_LEVELS = {"low", "high", "critical", "unknown"}
ALLOWED_TOOL_STATUSES = {"success", "empty", "failed"}
FORBIDDEN_ACTION_TERMS = (
    "修改plc",
    "自动启动",
    "自动停机",
    "绕过联锁",
    "旁路安全",
)


@dataclass(frozen=True)
class PlanValidationReport:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()


class MaintenancePlanValidator:
    version = "1.0"

    def validate(self, plan: MaintenancePlan) -> PlanValidationReport:
        errors: list[str] = []
        warnings: list[str] = []
        if not plan.request_id or not plan.session_id or not plan.equipment_id:
            errors.append("方案缺少请求、会话或设备标识")
        if plan.status not in ALLOWED_STATUSES:
            errors.append(f"方案状态不受支持：{plan.status}")
        if plan.risk_level not in ALLOWED_RISK_LEVELS:
            errors.append(f"风险等级不受支持：{plan.risk_level}")
        if not plan.requires_human_confirmation:
            errors.append("维修方案必须要求人工确认")
        if not plan.safety_warnings:
            errors.append("方案缺少安全警告")
        if any(not item.source_name.strip() for item in plan.evidence):
            errors.append("存在未标明来源的证据")
        invalid_traces = [item.tool for item in plan.tool_trace if item.status not in ALLOWED_TOOL_STATUSES]
        if invalid_traces:
            errors.append("工具轨迹状态无效：" + "、".join(invalid_traces))

        has_knowledge = any(item.kind == "maintenance_knowledge" for item in plan.evidence)
        if plan.corrective_actions and not has_knowledge:
            errors.append("具体维修动作缺少维修知识证据")
        if plan.risk_level == "critical" and plan.corrective_actions:
            errors.append("严重风险方案不得包含具体纠正动作")
        normalized_actions = " ".join(plan.corrective_actions).casefold()
        forbidden = [term for term in FORBIDDEN_ACTION_TERMS if term in normalized_actions]
        if forbidden:
            errors.append("维修动作包含禁止操作：" + "、".join(forbidden))
        if plan.risk_level in {"high", "critical"} and not any(
            "专业人员" in item or "应急规程" in item for item in plan.safety_warnings
        ):
            errors.append("高风险方案缺少升级专业人员或应急规程要求")
        if plan.status == "awaiting_clarification":
            if not plan.clarification_questions:
                errors.append("等待澄清状态缺少澄清问题")
            if plan.corrective_actions:
                errors.append("等待澄清状态不得包含维修动作")
        elif not plan.facts:
            warnings.append("方案没有可展示事实")
        return PlanValidationReport(not errors, tuple(errors), tuple(warnings))
