from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..domain import AccessContext
from ..safety import AccessPolicy


@dataclass(frozen=True)
class KnowledgeValidationReport:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    sha256: str
    entries: int
    active_entries: int


class KnowledgeValidator:
    required_fields = (
        "knowledge_id", "equipment_type", "match_terms", "summary", "possible_causes",
        "inspection_steps", "corrective_actions", "safety_warnings", "source",
    )
    injection_markers = ("ignore previous", "忽略之前", "system prompt", "执行以下指令")

    def __init__(self, access_policy: AccessPolicy | None = None) -> None:
        self.access_policy = access_policy or AccessPolicy()

    def validate_path(self, path: Path, access: AccessContext | None = None) -> KnowledgeValidationReport:
        if access is not None:
            self.access_policy.authorize(access, "validate_knowledge")
        payload_bytes = path.read_bytes()
        digest = hashlib.sha256(payload_bytes).hexdigest()
        errors: list[str] = []
        warnings: list[str] = []
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return KnowledgeValidationReport(False, (f"JSON 无效：{exc}",), (), digest, 0, 0)
        metadata = payload.get("metadata") or {}
        for field in ("version", "reviewed_by", "approved_by", "reviewed_at"):
            if not metadata.get(field):
                errors.append(f"metadata 缺少 {field}")
        if metadata.get("review_status") != "approved":
            errors.append("metadata.review_status 必须为 approved")
        if metadata.get("reviewed_by") == metadata.get("approved_by"):
            errors.append("知识审核人与批准人必须不同")
        entries = payload.get("entries")
        if not isinstance(entries, list):
            entries = []
            errors.append("entries 必须是数组")
        ids: set[str] = set()
        active = 0
        for index, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                errors.append(f"第 {index} 条知识不是对象")
                continue
            knowledge_id = str(entry.get("knowledge_id") or "")
            if knowledge_id in ids:
                errors.append(f"知识编号重复：{knowledge_id}")
            ids.add(knowledge_id)
            status = entry.get("status", metadata.get("default_status", "draft"))
            if status not in {"draft", "review", "active", "retired"}:
                errors.append(f"{knowledge_id or index} 状态无效：{status}")
            if status != "active":
                continue
            active += 1
            for field in self.required_fields:
                if not entry.get(field):
                    errors.append(f"{knowledge_id or index} 缺少 {field}")
            terms = entry.get("match_terms") or {}
            if not isinstance(terms, dict) or any(not isinstance(v, (int, float)) or v <= 0 for v in terms.values()):
                errors.append(f"{knowledge_id or index} 的 match_terms 权重必须为正数")
            source = entry.get("source") or {}
            if not all(source.get(key) for key in ("name", "url", "location")):
                errors.append(f"{knowledge_id or index} 的来源信息不完整")
            elif not str(source["url"]).startswith("https://"):
                errors.append(f"{knowledge_id or index} 的来源必须使用 HTTPS")
            serialized = json.dumps(entry, ensure_ascii=False).casefold()
            if any(marker in serialized for marker in self.injection_markers):
                errors.append(f"{knowledge_id or index} 含疑似提示注入文本")
        if active == 0:
            warnings.append("没有 active 知识条目")
        return KnowledgeValidationReport(not errors, tuple(errors), tuple(warnings), digest, len(entries), active)
