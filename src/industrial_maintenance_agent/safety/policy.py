from __future__ import annotations


class SafetyPolicy:
    BASE_WARNINGS = (
        "本结果是初步排查草稿，不能替代对应型号手册和合格维修人员。",
        "拆卸、接线或接触旋转部件前，必须停机、断电、卸压并防止意外启动。",
    )

    def apply(self, warnings: list[str], risk_level: str) -> list[str]:
        result = list(self.BASE_WARNINGS)
        if risk_level in {"high", "critical"}:
            result.append("当前风险不应继续由 Agent 自动判断运行条件，请升级给现场专业人员。")
        return list(dict.fromkeys((*result, *warnings)))
