from __future__ import annotations

from ..domain import AccessContext


ROLE_ACTIONS = {
    "technician": {"diagnose"},
    "domain_expert": {"diagnose", "review", "validate_knowledge"},
    "knowledge_admin": {"validate_knowledge", "publish_knowledge"},
    "administrator": {"diagnose", "review", "validate_knowledge", "publish_knowledge"},
}


class AccessPolicy:
    version = "1.0"

    def authorize(self, context: AccessContext, action: str, site_id: str | None = None) -> None:
        allowed_actions = ROLE_ACTIONS.get(context.role)
        if allowed_actions is None or action not in allowed_actions:
            raise PermissionError(f"角色 {context.role} 无权执行 {action}")
        if site_id is not None and "*" not in context.allowed_sites and site_id not in context.allowed_sites:
            raise PermissionError(f"身份无权访问站点：{site_id}")
