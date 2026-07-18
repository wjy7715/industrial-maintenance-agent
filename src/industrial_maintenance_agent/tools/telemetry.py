from __future__ import annotations

from typing import Any

from ..repositories import EquipmentRepository


class TelemetryTool:
    name = "query_telemetry"

    def __init__(self, repository: EquipmentRepository) -> None:
        self.repository = repository

    def run(self, equipment_id: str) -> dict[str, Any]:
        record = self.repository.get(equipment_id)
        if record is None:
            raise LookupError(f"未找到设备：{equipment_id}")
        return {
            "equipment_type": record["equipment_type"],
            "captured_at": record["captured_at"],
            "values": record["latest_telemetry"],
        }
