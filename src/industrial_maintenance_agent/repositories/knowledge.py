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

    def search(self, equipment_type: str, query: str, limit: int = 4) -> list[dict[str, Any]]:
        text = query.casefold()
        ranked: list[tuple[int, dict[str, Any]]] = []
        for entry in self._entries:
            if entry["equipment_type"] != equipment_type:
                continue
            score = sum(
                weight for term, weight in entry["match_terms"].items()
                if term.casefold() in text
            )
            if score > 0:
                ranked.append((score, entry))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["knowledge_id"]))
        return [entry for _, entry in ranked[:limit]]
