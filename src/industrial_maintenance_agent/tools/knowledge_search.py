from __future__ import annotations

from typing import Any

from ..repositories import KnowledgeRepository


class KnowledgeSearchTool:
    name = "search_maintenance_knowledge"

    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def run(self, equipment_type: str, symptoms: tuple[str, ...]) -> list[dict[str, Any]]:
        return self.repository.search(equipment_type, " ".join(symptoms))
