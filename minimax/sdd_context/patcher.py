"""应用模型输出：路径校验、备份、写盘、生成统一 diff。"""

from __future__ import annotations

import difflib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from sdd_context.seekstore import SeekStore


def apply_change(
    project_dir: Path,
    parsed: dict[str, Any],
    data_dir: Path,
    allowed_paths: set[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = Path(data_dir) / "backups" / stamp
    changed: list[dict[str, Any]] = []
    diff_parts: list[str] = []

    for item in parsed.get("files", []):
        rel = str(item.get("path", "")).strip().lstrip("./")
        new_content = item.get("content")
        if not rel or not isinstance(new_content, str):
            raise ValueError(f"非法的返回文件项：path={rel!r}")
        target = (project_dir / rel).resolve()
        if not str(target).startswith(str(project_dir.resolve()) + "/"):
            raise ValueError(f"越界路径被拒绝：{rel}")
        if allowed_paths is not None and rel not in allowed_paths:
            raise ValueError(f"文件不在上下文允许列表中：{rel}")
        if not target.exists():
            raise ValueError(f"目标文件不存在（只允许修改既有文件）：{rel}")
        old_text = target.read_text(encoding="utf-8")
        if not new_content.endswith("\n"):
            new_content += "\n"
        if SeekStore.content_sha(old_text) == SeekStore.content_sha(new_content):
            changed.append({"path": rel, "status": "unchanged"})
            continue
        diff = "".join(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
        diff_parts.append(diff)
        record = {"path": rel, "status": "modified", "diff": diff}
        if not dry_run:
            backup_dir = backup_root / Path(rel).parent
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_dir / Path(rel).name)
            target.write_text(new_content, encoding="utf-8")
            record["backup"] = str(backup_root / rel)
        changed.append(record)

    return {
        "summary": parsed.get("summary", ""),
        "dry_run": dry_run,
        "changed": changed,
        "diff": "".join(diff_parts),
        "backup_root": None if dry_run else str(backup_root),
    }


def restore(project_dir: Path, backup_root: str, rel: str) -> None:
    source = Path(backup_root) / rel
    shutil.copy2(source, Path(project_dir) / rel)
