from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from ..repositories import KnowledgeRepository


@dataclass(frozen=True)
class BlindEvaluationReport:
    dataset_version: str
    total: int
    correct: int
    accuracy: float
    false_positive: int
    false_negative: int
    wrong_match: int
    latency_p50_ms: float
    latency_p95_ms: float
    latency_max_ms: float
    failures: tuple[dict[str, Any], ...]
    scope_notice: str = "本地保留集检索结果与进程内延迟，不代表现场诊断准确率或生产性能。"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_blind_evaluation(root: Path, repetitions: int = 5) -> BlindEvaluationReport:
    repository = KnowledgeRepository(root / "data" / "knowledge" / "pump_troubleshooting.json")
    with (root / "data" / "evaluation" / "blind_cases.json").open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    cases = payload["cases"]
    repetitions = max(1, min(int(repetitions), 100))
    latencies: list[float] = []
    failures: list[dict[str, Any]] = []
    false_positive = false_negative = wrong_match = correct = 0
    for case in cases:
        actual: str | None = None
        for _ in range(repetitions):
            started = perf_counter()
            results = repository.search("centrifugal_pump", case["text"], limit=3)
            latencies.append((perf_counter() - started) * 1000)
            actual = results[0]["knowledge_id"] if results else None
        expected = case["expected"]
        if actual == expected:
            correct += 1
            continue
        if expected is None and actual is not None:
            category = "false_positive"
            false_positive += 1
        elif expected is not None and actual is None:
            category = "false_negative"
            false_negative += 1
        else:
            category = "wrong_match"
            wrong_match += 1
        failures.append({"id": case["id"], "category": category, "expected": expected, "actual": actual})
    ordered = sorted(latencies)
    return BlindEvaluationReport(
        dataset_version=str(payload["metadata"]["version"]),
        total=len(cases), correct=correct,
        accuracy=round(correct / len(cases), 4) if cases else 0.0,
        false_positive=false_positive, false_negative=false_negative, wrong_match=wrong_match,
        latency_p50_ms=_percentile(ordered, 0.50),
        latency_p95_ms=_percentile(ordered, 0.95),
        latency_max_ms=round(max(ordered), 4) if ordered else 0.0,
        failures=tuple(failures),
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int((len(values) - 1) * percentile)))
    return round(values[index], 4)
