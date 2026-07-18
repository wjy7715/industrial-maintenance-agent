from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..repositories import KnowledgeRepository


@dataclass(frozen=True)
class EvaluationReport:
    total: int
    top1_correct: int
    top3_correct: int
    no_match: int
    top1_accuracy: float
    top3_accuracy: float
    failures: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_retrieval_evaluation(root: Path) -> EvaluationReport:
    repository = KnowledgeRepository(root / "data" / "knowledge" / "pump_troubleshooting.json")
    with (root / "data" / "evaluation" / "cases.json").open("r", encoding="utf-8") as handle:
        cases = json.load(handle)["cases"]
    top1 = 0
    top3 = 0
    no_match = 0
    failures: list[dict[str, object]] = []
    for case in cases:
        results = repository.search("centrifugal_pump", case["text"], limit=3)
        ids = [item["knowledge_id"] for item in results]
        if not ids:
            no_match += 1
        if ids and ids[0] == case["expected"]:
            top1 += 1
        else:
            failures.append({"id": case["id"], "expected": case["expected"], "actual": ids})
        if case["expected"] in ids:
            top3 += 1
    total = len(cases)
    return EvaluationReport(
        total, top1, top3, no_match,
        round(top1 / total, 4) if total else 0.0,
        round(top3 / total, 4) if total else 0.0,
        tuple(failures),
    )
