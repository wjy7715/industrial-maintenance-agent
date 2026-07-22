from __future__ import annotations

from datetime import datetime
from typing import Any


def summarize_trend(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a deterministic trend summary without predicting failures."""
    if not records:
        return {"status": "empty", "points": 0, "metrics": {}, "quality_warnings": ["没有趋势数据"]}
    ordered = sorted(records, key=lambda item: datetime.fromisoformat(item["captured_at"]))
    timestamps = [datetime.fromisoformat(item["captured_at"]) for item in ordered]
    warnings: list[str] = []
    if any(item.tzinfo is None for item in timestamps):
        warnings.append("存在无时区时间戳")
    gaps = [
        (timestamps[index] - timestamps[index - 1]).total_seconds()
        for index in range(1, len(timestamps))
    ]
    if gaps and max(gaps) > 2 * 3600:
        warnings.append("相邻采样间隔超过 2 小时，趋势可能不连续")
    metrics: dict[str, dict[str, Any]] = {}
    for name in ordered[-1]["latest_telemetry"]:
        values = [float(item["latest_telemetry"][name]) for item in ordered]
        change = values[-1] - values[0]
        metrics[name] = {
            "first": values[0],
            "latest": values[-1],
            "minimum": min(values),
            "maximum": max(values),
            "change": round(change, 4),
            "direction": "rising" if change > 0 else ("falling" if change < 0 else "stable"),
        }
    return {
        "status": "limited" if warnings or len(ordered) < 3 else "good",
        "points": len(ordered),
        "captured_at_start": ordered[0]["captured_at"],
        "captured_at_end": ordered[-1]["captured_at"],
        "metrics": metrics,
        "quality_warnings": warnings + (["少于 3 个采样点，仅展示变化，不判断趋势"] if len(ordered) < 3 else []),
    }
