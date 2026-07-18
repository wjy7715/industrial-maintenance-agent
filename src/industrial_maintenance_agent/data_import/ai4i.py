from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any


AI4I_COLUMNS = {
    "UDI", "Product ID", "Type", "Air temperature [K]", "Process temperature [K]",
    "Rotational speed [rpm]", "Torque [Nm]", "Tool wear [min]", "Machine failure",
    "TWF", "HDF", "PWF", "OSF", "RNF",
}


def profile_ai4i(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual = set(reader.fieldnames or [])
        missing = sorted(AI4I_COLUMNS - actual)
        if missing:
            raise ValueError("AI4I 数据缺少字段：" + ", ".join(missing))
        rows = 0
        failures = 0
        modes: Counter[str] = Counter()
        for row in reader:
            rows += 1
            failures += int(row["Machine failure"])
            for mode in ("TWF", "HDF", "PWF", "OSF", "RNF"):
                modes[mode] += int(row[mode])
    return {
        "rows": rows,
        "machine_failures": failures,
        "failure_rate": round(failures / rows, 6) if rows else 0.0,
        "failure_modes": dict(modes),
        "source": "UCI AI4I 2020",
        "license": "CC BY 4.0",
    }
