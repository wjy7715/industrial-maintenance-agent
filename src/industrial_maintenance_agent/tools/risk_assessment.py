from __future__ import annotations

from typing import Any

from ..domain import validate_units


class RiskAssessmentTool:
    name = "assess_operating_risk"
    version = "1.4"

    PUMP_THRESHOLDS = {
        "vibration_mm_s": (4.5, 7.1),
        "temperature_c": (65.0, 80.0),
    }

    def run(
        self,
        equipment_type: str,
        telemetry: dict[str, Any],
        units: dict[str, str],
    ) -> dict[str, Any]:
        if equipment_type != "centrifugal_pump":
            return {"level": "unknown", "signals": [], "notice": "该设备类型尚无阈值规则"}
        validate_units(equipment_type, units)
        level = "low"
        signals: list[str] = []
        for field, (warning, critical) in self.PUMP_THRESHOLDS.items():
            value = telemetry.get(field)
            if not isinstance(value, (int, float)):
                continue
            if value >= critical:
                level = "critical"
                signals.append(
                    f"{field}={value} {units[field]} 达到演示临界阈值 "
                    f"{critical} {units[field]}"
                )
            elif value >= warning:
                if level != "critical":
                    level = "high"
                signals.append(
                    f"{field}={value} {units[field]} 超出演示告警阈值 "
                    f"{warning} {units[field]}"
                )
        return {
            "level": level,
            "signals": signals,
            "notice": "阈值仅用于原型演示，不能替代具体型号和现场标准",
        }

    def result_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": {"kind": "deterministic_rule", "name": "项目演示阈值规则"},
            "quality": "good" if data["level"] != "unknown" else "unknown",
            "warnings": [data["notice"]],
        }
