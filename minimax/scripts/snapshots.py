#!/usr/bin/env python3
"""把 step8 的运行记录展开成“修改前/修改后”代码快照目录，便于评审直接对比。

用法：python3 scripts/snapshots.py <step8_minimax_run.json> <evidence_dir> <project_dir>
产出：<evidence_dir>/code_before/<相对路径>、<evidence_dir>/code_after/<相对路径>
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def main(run_json: str, evidence_dir: str, project_dir: str) -> int:
    record = json.loads(Path(run_json).read_text(encoding="utf-8"))
    apply_result = record.get("apply_result", {})
    backup_root = apply_result.get("backup_root")
    evidence = Path(evidence_dir)
    project = Path(project_dir)
    before_dir = evidence / "code_before"
    after_dir = evidence / "code_after"
    written = []
    for item in apply_result.get("changed", []):
        if item.get("status") != "modified":
            continue
        rel = item["path"]
        after_file = project / rel
        if after_file.exists():
            target = after_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(after_file, target)
            written.append(str(target))
        if backup_root:
            before_file = Path(backup_root) / rel
            if before_file.exists():
                target = before_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(before_file, target)
                written.append(str(target))
    print(f"[snapshots] 写出 {len(written)} 个文件；修改前快照来自 patcher 备份 {backup_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
