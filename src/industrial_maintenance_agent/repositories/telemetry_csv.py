from __future__ import annotations

import csv
import io
import math
from datetime import datetime
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = {
    "site_id",
    "equipment_id",
    "equipment_type",
    "captured_at",
    "pressure_bar",
    "vibration_mm_s",
    "temperature_c",
    "rotation_rpm",
}
NUMERIC_COLUMNS = (
    "pressure_bar",
    "vibration_mm_s",
    "temperature_c",
    "rotation_rpm",
)


class TelemetryCsvRepository:
    """Read-only adapter for a user-provided, de-identified telemetry snapshot."""

    max_bytes = 5 * 1024 * 1024
    max_rows = 10_000

    def __init__(self, path: Path) -> None:
        payload = path.read_bytes()
        self._load(payload, path.name)

    @classmethod
    def from_bytes(cls, payload: bytes, source_name: str = "uploaded_telemetry.csv") -> "TelemetryCsvRepository":
        instance = cls.__new__(cls)
        instance._load(payload, Path(source_name).name)
        return instance

    def _load(self, payload: bytes, source_name: str) -> None:
        if not payload:
            raise ValueError("遥测 CSV 为空")
        if len(payload) > self.max_bytes:
            raise ValueError(f"遥测 CSV 超过 {self.max_bytes // 1024 // 1024} MB 限制")
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("遥测 CSV 必须使用 UTF-8 编码") from exc

        reader = csv.DictReader(io.StringIO(text))
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError("遥测 CSV 缺少字段：" + "、".join(missing))

        records: dict[str, dict[str, Any]] = {}
        for row_number, row in enumerate(reader, start=2):
            if row_number - 1 > self.max_rows:
                raise ValueError(f"遥测 CSV 超过 {self.max_rows} 行限制")
            equipment_id = (row.get("equipment_id") or "").strip()
            site_id = (row.get("site_id") or "").strip()
            equipment_type = (row.get("equipment_type") or "").strip()
            captured_at = (row.get("captured_at") or "").strip()
            if not equipment_id or not equipment_type or not site_id:
                raise ValueError(f"第 {row_number} 行站点、设备编号或类型为空")
            if equipment_id in records:
                raise ValueError(f"设备编号重复：{equipment_id}")
            try:
                datetime.fromisoformat(captured_at)
            except ValueError as exc:
                raise ValueError(f"第 {row_number} 行 captured_at 不是 ISO 8601 时间") from exc

            values: dict[str, float] = {}
            for column in NUMERIC_COLUMNS:
                try:
                    value = float((row.get(column) or "").strip())
                except ValueError as exc:
                    raise ValueError(f"第 {row_number} 行 {column} 不是数值") from exc
                if not math.isfinite(value):
                    raise ValueError(f"第 {row_number} 行 {column} 必须是有限数值")
                values[column] = value

            active_errors = [
                item.strip()
                for item in (row.get("active_errors") or "").split(";")
                if item.strip()
            ]
            records[equipment_id] = {
                "equipment_id": equipment_id,
                "site_id": site_id,
                "equipment_type": equipment_type,
                "equipment_model": (row.get("equipment_model") or "").strip() or None,
                "captured_at": captured_at,
                "latest_telemetry": values,
                "active_errors": active_errors,
                "maintenance_history": [],
            }

        if not records:
            raise ValueError("遥测 CSV 没有数据行")
        self.metadata = {
            "kind": "user_imported_read_only",
            "name": source_name,
            "notice": "用户提供的脱敏只读快照；系统未独立核验其现场真实性。",
            "schema_version": "1.0",
        }
        self._records = records

    def get(self, equipment_id: str) -> dict[str, Any] | None:
        return self._records.get(equipment_id)

    def list_equipment(self) -> list[dict[str, Any]]:
        return list(self._records.values())

    def get_scope(self, equipment_id: str) -> str | None:
        record = self.get(equipment_id)
        return str(record.get("site_id")) if record else None

    def validation_summary(self) -> dict[str, Any]:
        timestamps = [item["captured_at"] for item in self._records.values()]
        return {
            "status": "valid",
            "source": self.metadata,
            "rows": len(self._records),
            "equipment_ids": sorted(self._records),
            "captured_at_min": min(timestamps),
            "captured_at_max": max(timestamps),
            "write_back_enabled": False,
        }
