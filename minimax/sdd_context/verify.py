"""测试执行与留痕：命令、退出码、对应代码版本（内容哈希）都写入日志。"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sdd_context.seekstore import SeekStore


def _git_version(project_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or "n/a"
    except Exception:
        return "n/a"


def run_suite(project_dir: Path, test_file: str, label: str) -> dict[str, Any]:
    project_dir = Path(project_dir)
    target = project_dir / test_file
    command = [sys.executable, "-m", "pytest", test_file, "-v", "--no-header", "-o", "addopts="]
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    process = subprocess.run(command, cwd=project_dir, capture_output=True, text=True, timeout=600)
    output = process.stdout + ("\n" + process.stderr if process.stderr else "")
    return {
        "label": label,
        "suite": test_file,
        "command": " ".join(command),
        "cwd": str(project_dir),
        "started_at": started,
        "exit_code": process.returncode,
        "passed": process.returncode == 0,
        "code_version_git": _git_version(project_dir),
        "file_sha256": {test_file: SeekStore.content_sha(target.read_text(encoding="utf-8")) if target.exists() else "missing"},
        "output": output,
    }


def run_all(project_dir: Path, target_file: str, regression_files: list[str]) -> dict[str, Any]:
    suites = [run_suite(project_dir, target_file, "target")]
    suites += [run_suite(project_dir, regression_file, "regression") for regression_file in regression_files]
    return {
        "project": str(project_dir),
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "suites": suites,
        "all_passed": all(suite["passed"] for suite in suites),
        "summary": {
            suite["label"] + ":" + suite["suite"]: {"exit_code": suite["exit_code"], "passed": suite["passed"]}
            for suite in suites
        },
    }
