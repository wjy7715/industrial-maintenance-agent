from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetricDefinition:
    unit: str
    minimum: float
    maximum: float


PUMP_TELEMETRY_SCHEMA = {
    "pressure_bar": MetricDefinition("bar", 0.0, 100.0),
    "vibration_mm_s": MetricDefinition("mm/s", 0.0, 100.0),
    "temperature_c": MetricDefinition("°C", -50.0, 250.0),
    "rotation_rpm": MetricDefinition("rpm", 0.0, 100_000.0),
}


def telemetry_schema(equipment_type: str) -> dict[str, MetricDefinition]:
    if equipment_type != "centrifugal_pump":
        raise ValueError(f"设备类型尚无遥测单位契约：{equipment_type}")
    return PUMP_TELEMETRY_SCHEMA


def validate_telemetry_values(
    equipment_type: str,
    values: dict[str, Any],
) -> dict[str, str]:
    schema = telemetry_schema(equipment_type)
    missing = sorted(set(schema) - set(values))
    unknown = sorted(set(values) - set(schema))
    if missing:
        raise ValueError("遥测缺少指标：" + "、".join(missing))
    if unknown:
        raise ValueError("遥测包含未注册指标：" + "、".join(unknown))
    for field, definition in schema.items():
        value = values[field]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError(f"遥测 {field} 必须是有限数值")
        if not definition.minimum <= float(value) <= definition.maximum:
            raise ValueError(
                f"遥测 {field}={value} 超出允许范围 "
                f"[{definition.minimum}, {definition.maximum}] {definition.unit}"
            )
    return {field: definition.unit for field, definition in schema.items()}


def validate_units(equipment_type: str, units: dict[str, str]) -> None:
    expected = {field: item.unit for field, item in telemetry_schema(equipment_type).items()}
    if units != expected:
        raise ValueError(f"遥测单位不匹配：期望 {expected}，实际 {units}")
