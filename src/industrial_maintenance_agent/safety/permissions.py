from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ToolPermission:
    tool_name: str
    operation: str
    decision: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


DEFAULT_TOOL_PERMISSIONS = (
    ToolPermission("query_telemetry", "read", "allow", "只读查询标准化遥测"),
    ToolPermission("query_fault_history", "read", "allow", "只读查询故障与维修历史"),
    ToolPermission("assess_operating_risk", "compute", "allow", "本地确定性规则计算"),
    ToolPermission("search_maintenance_knowledge", "read", "allow", "只读检索已发布知识"),
    ToolPermission("record_audit", "local_audit", "allow", "本地审计记录，不调用外部系统"),
    ToolPermission("write_cmms_work_order", "external_write", "confirm", "外部工单写入必须逐次确认"),
    ToolPermission("control_plc", "device_control", "deny", "本项目禁止设备控制"),
)


class ToolPermissionRegistry:
    version = "1.0"

    def __init__(self, permissions: tuple[ToolPermission, ...] = DEFAULT_TOOL_PERMISSIONS) -> None:
        self._permissions = {item.tool_name: item for item in permissions}

    def authorize(self, tool_name: str, confirmed: bool = False) -> ToolPermission:
        permission = self._permissions.get(tool_name)
        if permission is None:
            raise PermissionError(f"工具未注册，默认拒绝：{tool_name}")
        if permission.decision == "deny":
            raise PermissionError(f"工具被策略禁止：{tool_name}；{permission.reason}")
        if permission.decision == "confirm" and not confirmed:
            raise PermissionError(f"工具需要明确确认：{tool_name}；{permission.reason}")
        return permission

    def report(self) -> list[dict[str, str]]:
        return [item.to_dict() for item in self._permissions.values()]
