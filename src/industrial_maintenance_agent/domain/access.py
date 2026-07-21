from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccessContext:
    actor_id: str
    role: str
    allowed_sites: tuple[str, ...]
    identity_source: str = "local_demo"

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ValueError("actor_id 不能为空")
        if not self.role.strip():
            raise ValueError("role 不能为空")
        if not self.allowed_sites:
            raise ValueError("allowed_sites 不能为空")

    @classmethod
    def local_technician(cls) -> "AccessContext":
        return cls(
            "local-technician",
            "technician",
            ("demo-site", "local-upload"),
        )
