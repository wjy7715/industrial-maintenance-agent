from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..repositories import EquipmentDataSource


class TelemetryTool:
    name = "query_telemetry"
    version = "1.2"
    stale_after_hours = 24

    def __init__(self, repository: EquipmentDataSource) -> None:
        self.repository = repository

    def run(self, equipment_id: str) -> dict[str, Any]:
        record = self.repository.get(equipment_id)
        if record is None:
            raise LookupError(f"未找到设备：{equipment_id}")
        return {
            "equipment_type": record["equipment_type"],
            "equipment_model": record.get("equipment_model"),
            "captured_at": record["captured_at"],
            "values": record["latest_telemetry"],
        }

    def result_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        captured_at = datetime.fromisoformat(data["captured_at"])
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        age_hours = (
            datetime.now(timezone.utc) - captured_at.astimezone(timezone.utc)
        ).total_seconds() / 3600
        future = age_hours < -(5 / 60)
        stale = age_hours > self.stale_after_hours
        metadata = getattr(self.repository, "metadata", {})
        source = {
            "kind": metadata.get("kind", "unknown"),
            "name": metadata.get("name") or metadata.get("notice") or "未命名遥测数据源",
        }
        warnings: list[str] = []
        if future:
            warnings.append("遥测时间晚于系统时间超过 5 分钟，请核对设备时钟与时区")
        elif stale:
            warnings.append(f"遥测数据已超过 {self.stale_after_hours} 小时")
        return {
            "source": source,
            "observed_at": data["captured_at"],
            "quality": "suspicious" if future else ("stale" if stale else "good"),
            "warnings": warnings,
        }
