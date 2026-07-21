from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Protocol


class RunnableTool(Protocol):
    name: str

    def run(self, *args: Any, **kwargs: Any) -> Any: ...


class ToolAuthorizer(Protocol):
    def authorize(self, tool_name: str, confirmed: bool = False) -> Any: ...


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    tool_version: str
    status: str
    data: Any = None
    source: dict[str, Any] = field(default_factory=dict)
    observed_at: str | None = None
    quality: str = "unknown"
    warnings: tuple[str, ...] = ()
    error: str | None = None
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def execute_tool(
    tool: RunnableTool,
    *args: Any,
    permission_registry: ToolAuthorizer | None = None,
    confirmed: bool = False,
    **kwargs: Any,
) -> ToolResult:
    started = datetime.now(timezone.utc)
    started_clock = perf_counter()
    try:
        if permission_registry is not None:
            permission_registry.authorize(tool.name, confirmed=confirmed)
        data = tool.run(*args, **kwargs)
        empty_check = getattr(tool, "is_empty", None)
        is_empty = empty_check(data) if callable(empty_check) else data in (None, [], {})
        status = "empty" if is_empty else "success"
        error = None
    except Exception as exc:  # tools are an external boundary and must fail closed
        data = None
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
    finished = datetime.now(timezone.utc)
    metadata = _metadata(tool, data)
    return ToolResult(
        tool_name=tool.name,
        tool_version=str(getattr(tool, "version", "1.0")),
        status=status,
        data=data,
        source=metadata["source"],
        observed_at=metadata["observed_at"],
        quality=metadata["quality"],
        warnings=tuple(metadata["warnings"]),
        error=error,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        duration_ms=round((perf_counter() - started_clock) * 1000, 3),
    )


def _metadata(tool: RunnableTool, data: Any) -> dict[str, Any]:
    provider = getattr(tool, "result_metadata", None)
    if callable(provider) and data is not None:
        supplied = provider(data)
        return {
            "source": supplied.get("source", {}),
            "observed_at": supplied.get("observed_at"),
            "quality": supplied.get("quality", "unknown"),
            "warnings": supplied.get("warnings", []),
        }
    return {"source": {}, "observed_at": None, "quality": "unknown", "warnings": []}
