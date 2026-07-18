from __future__ import annotations

import json
from typing import Any


class HermesNarrator:
    """Optional Hermes presentation adapter; deterministic plan remains authoritative."""

    def __init__(self, model: str = "") -> None:
        self.model = model

    def available(self) -> bool:
        try:
            from run_agent import AIAgent  # noqa: F401
        except ImportError:
            return False
        return True

    def render(self, plan: dict[str, Any]) -> str:
        try:
            from run_agent import AIAgent
        except ImportError as exc:
            raise RuntimeError("未安装 Hermes Agent；请使用离线结构化输出") from exc
        agent = AIAgent(
            model=self.model,
            quiet_mode=True,
            disabled_toolsets=["terminal", "web", "browser", "file"],
            ephemeral_system_prompt=(
                "你是工业运维结果整理器。只能改写给定 JSON，不得新增原因、步骤或执行结果；"
                "必须保留草稿、来源和人工确认边界。"
            ),
        )
        return agent.chat("请整理以下已验证方案：\n" + json.dumps(plan, ensure_ascii=False))
