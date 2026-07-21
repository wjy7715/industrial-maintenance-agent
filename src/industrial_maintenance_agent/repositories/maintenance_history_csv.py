from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = {"event_id", "equipment_id", "event_type", "event_at"}
EVENT_TYPES = {"alarm_open", "alarm_close", "maintenance_closed"}


class MaintenanceHistoryCsvRepository:
    """Read-only adapter for de-identified alarm and maintenance closure events."""

    max_bytes = 5 * 1024 * 1024
    max_rows = 10_000

    def __init__(self, path: Path) -> None:
        self._load(path.read_bytes(), path.name)

    @classmethod
    def from_bytes(
        cls,
        payload: bytes,
        source_name: str = "uploaded_maintenance_history.csv",
    ) -> "MaintenanceHistoryCsvRepository":
        instance = cls.__new__(cls)
        instance._load(payload, Path(source_name).name)
        return instance

    def _load(self, payload: bytes, source_name: str) -> None:
        if not payload:
            raise ValueError("故障历史 CSV 为空")
        if len(payload) > self.max_bytes:
            raise ValueError(f"故障历史 CSV 超过 {self.max_bytes // 1024 // 1024} MB 限制")
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("故障历史 CSV 必须使用 UTF-8 编码") from exc

        reader = csv.DictReader(io.StringIO(text))
        missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames or []))
        if missing:
            raise ValueError("故障历史 CSV 缺少字段：" + "、".join(missing))

        events: list[dict[str, Any]] = []
        event_ids: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            if row_number - 1 > self.max_rows:
                raise ValueError(f"故障历史 CSV 超过 {self.max_rows} 行限制")
            event_id = _required(row, "event_id", row_number)
            equipment_id = _required(row, "equipment_id", row_number)
            event_type = _required(row, "event_type", row_number)
            event_at = _timestamp(row, "event_at", row_number)
            if event_id in event_ids:
                raise ValueError(f"事件编号重复：{event_id}")
            if event_type not in EVENT_TYPES:
                raise ValueError(f"第 {row_number} 行 event_type 不受支持：{event_type}")
            event_ids.add(event_id)

            event = {
                "event_id": event_id,
                "equipment_id": equipment_id,
                "event_type": event_type,
                "event_at": event_at.isoformat(),
                "_sort_at": event_at.astimezone(timezone.utc),
            }
            if event_type in {"alarm_open", "alarm_close"}:
                event["error_code"] = _required(row, "error_code", row_number)
            else:
                event["action"] = _required(row, "action", row_number)
                event["result"] = _required(row, "result", row_number)
                verified_at = _timestamp(row, "verified_at", row_number)
                if verified_at.astimezone(timezone.utc) < event_at.astimezone(timezone.utc):
                    raise ValueError(f"第 {row_number} 行 verified_at 早于维修事件时间")
                event["verified_at"] = verified_at.isoformat()
                event["confirmed_cause"] = (row.get("confirmed_cause") or "").strip() or None
            events.append(event)

        if not events:
            raise ValueError("故障历史 CSV 没有数据行")
        events.sort(key=lambda item: (item["_sort_at"], item["event_id"]))

        records: dict[str, dict[str, Any]] = {}
        for event in events:
            record = records.setdefault(
                event["equipment_id"],
                {
                    "equipment_id": event["equipment_id"],
                    "active_errors": [],
                    "maintenance_history": [],
                },
            )
            if event["event_type"] == "alarm_open":
                if event["error_code"] not in record["active_errors"]:
                    record["active_errors"].append(event["error_code"])
            elif event["event_type"] == "alarm_close":
                if event["error_code"] in record["active_errors"]:
                    record["active_errors"].remove(event["error_code"])
            else:
                record["maintenance_history"].append(
                    {
                        "event_id": event["event_id"],
                        "date": event["event_at"],
                        "action": event["action"],
                        "result": event["result"],
                        "confirmed_cause": event["confirmed_cause"],
                        "verified_at": event["verified_at"],
                    }
                )

        self.metadata = {
            "kind": "user_imported_history_read_only",
            "name": source_name,
            "notice": "用户提供的脱敏故障与维修闭环记录；系统未独立核验。",
            "schema_version": "1.0",
        }
        self._records = records
        self._events = events

    def get(self, equipment_id: str) -> dict[str, Any] | None:
        return self._records.get(equipment_id)

    def list_equipment(self) -> list[dict[str, Any]]:
        return list(self._records.values())

    def validation_summary(self) -> dict[str, Any]:
        return {
            "status": "valid",
            "source": self.metadata,
            "events": len(self._events),
            "equipment_ids": sorted(self._records),
            "active_alarm_count": sum(len(item["active_errors"]) for item in self._records.values()),
            "closed_maintenance_count": sum(
                len(item["maintenance_history"]) for item in self._records.values()
            ),
            "write_back_enabled": False,
        }


def _required(row: dict[str, str | None], field: str, row_number: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise ValueError(f"第 {row_number} 行 {field} 为空")
    return value


def _timestamp(row: dict[str, str | None], field: str, row_number: int) -> datetime:
    value = _required(row, field, row_number)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"第 {row_number} 行 {field} 不是 ISO 8601 时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"第 {row_number} 行 {field} 必须包含时区")
    return parsed
