from __future__ import annotations

from typing import Any

from ..repositories import KnowledgeRepository


class KnowledgeSearchTool:
    name = "search_maintenance_knowledge"
    version = "1.1"

    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def run(
        self,
        equipment_type: str,
        symptoms: tuple[str, ...],
        equipment_model: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.repository.search(equipment_type, " ".join(symptoms), equipment_model=equipment_model)

    def result_metadata(self, data: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "source": {"kind": "curated_knowledge", "name": "版本化维修知识库"},
            "quality": "good" if data else "unknown",
        }
