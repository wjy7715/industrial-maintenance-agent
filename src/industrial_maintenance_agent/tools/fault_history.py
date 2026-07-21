from __future__ import annotations

from typing import Any

from ..repositories import EquipmentDataSource


class FaultHistoryTool:
    name = "query_fault_history"
    version = "1.2"

    def __init__(self, repository: EquipmentDataSource) -> None:
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
        metadata = getattr(self.repository, "metadata", {})
        return {
            "source": {
                "kind": metadata.get("kind", "unknown"),
                "name": metadata.get("name") or metadata.get("notice") or "未命名故障数据源",
            },
            "quality": "good",
        }

    @staticmethod
    def is_empty(data: dict[str, Any]) -> bool:
        return not data["active_errors"] and not data["maintenance_history"]
