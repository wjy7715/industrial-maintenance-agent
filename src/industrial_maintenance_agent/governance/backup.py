from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def create_sqlite_backup(source: Path, destination_dir: Path) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(f"审计数据库不存在：{source}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = destination_dir / f"assistant-{stamp}.db"
    counter = 1
    while destination.exists():
        destination = destination_dir / f"assistant-{stamp}-{counter}.db"
        counter += 1
    with closing(sqlite3.connect(source)) as source_db, closing(sqlite3.connect(destination)) as backup_db:
        source_db.backup(backup_db)
    integrity = _integrity(destination)
    if integrity != "ok":
        destination.unlink(missing_ok=True)
        raise ValueError(f"备份完整性检查失败：{integrity}")
    manifest = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_name": source.name,
        "backup_file": destination.name,
        "sha256": _sha256(destination),
        "size_bytes": destination.stat().st_size,
        "integrity_check": integrity,
    }
    manifest_path = destination.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**manifest, "backup_path": str(destination), "manifest_path": str(manifest_path)}


def verify_sqlite_backup(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup = manifest_path.parent / manifest["backup_file"]
    if not backup.is_file():
        raise FileNotFoundError(f"备份文件不存在：{backup}")
    actual_hash = _sha256(backup)
    if actual_hash != manifest["sha256"]:
        raise ValueError("备份哈希不匹配，文件可能已损坏或被修改")
    integrity = _integrity(backup)
    if integrity != "ok":
        raise ValueError(f"SQLite 完整性检查失败：{integrity}")
    return {"valid": True, "sha256": actual_hash, "integrity_check": integrity, "backup_path": str(backup)}


def restore_sqlite_backup(manifest_path: Path, target: Path) -> dict[str, Any]:
    """Restore only to a new file so recovery never overwrites live data."""
    if target.exists():
        raise FileExistsError(f"恢复目标已存在，拒绝覆盖：{target}")
    verification = verify_sqlite_backup(manifest_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(verification["backup_path"])) as backup_db, closing(sqlite3.connect(target)) as target_db:
        backup_db.backup(target_db)
    integrity = _integrity(target)
    if integrity != "ok":
        target.unlink(missing_ok=True)
        raise ValueError(f"恢复文件完整性检查失败：{integrity}")
    return {"restored": True, "target": str(target), "integrity_check": integrity}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else "missing result"
