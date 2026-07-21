from __future__ import annotations

from typing import Any

from ..repositories import EquipmentRepository


class FaultHistoryTool:
    name = "query_fault_history"
    version = "1.1"

    def __init__(self, repository: EquipmentRepository) -> None:
        self.repository = repository

    def run(self, equipment_id: str) -> dict[str, Any]:
        record = self.repository.get(equipment_id)
        if record is None:
            raise LookupError(f"未找到设备：{equipment_id}")
        return {
            "active_errors": record.get("active_errors", []),
            "maintenance_history": record.get("maintenance_history", []),
        }

    def result_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": {"kind": "synthetic_demo", "name": "项目仿真故障记录"},
            "quality": "good",
        }

    @staticmethod
    def is_empty(data: dict[str, Any]) -> bool:
        return not data["active_errors"] and not data["maintenance_history"]
