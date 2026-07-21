from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class KnowledgeRepository:
    def __init__(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.metadata = payload["metadata"]
        self._entries = payload["entries"]

    def search(
        self,
        equipment_type: str,
        query: str,
        limit: int = 4,
        equipment_model: str | None = None,
    ) -> list[dict[str, Any]]:
        text = query.casefold()
        ranked: list[tuple[int, dict[str, Any]]] = []
        for entry in self._entries:
            if entry["equipment_type"] != equipment_type:
                continue
            status = entry.get("status", self.metadata.get("default_status", "draft"))
            if status != "active":
                continue
            models = entry.get("applicable_models", self.metadata.get("applicable_models", ["*"]))
            if equipment_model and "*" not in models and equipment_model not in models:
                continue
            score = sum(
                weight for term, weight in entry["match_terms"].items()
                if term.casefold() in text
            )
            if score > 0:
                result = dict(entry)
                result["status"] = status
                result["knowledge_version"] = entry.get("version", self.metadata["version"])
                result["applicable_models"] = models
                ranked.append((score, result))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["knowledge_id"]))
        return [entry for _, entry in ranked[:limit]]
