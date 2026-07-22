from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class EquipmentDataSource(Protocol):
    metadata: dict[str, Any]

    def get(self, equipment_id: str) -> dict[str, Any] | None: ...

    def list_equipment(self) -> list[dict[str, Any]]: ...

    def get_scope(self, equipment_id: str) -> str | None: ...


class HistoryDataSource(Protocol):
    metadata: dict[str, Any]

    def get(self, equipment_id: str) -> dict[str, Any] | None: ...


class EquipmentRepository:
    def __init__(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.metadata = payload["metadata"]
        self._records = {item["equipment_id"]: item for item in payload["equipment"]}

    def get(self, equipment_id: str) -> dict[str, Any] | None:
        return self._records.get(equipment_id)

    def list_equipment(self) -> list[dict[str, Any]]:
        return list(self._records.values())

    def get_scope(self, equipment_id: str) -> str | None:
        record = self.get(equipment_id)
        return str(record.get("site_id")) if record and record.get("site_id") else None
