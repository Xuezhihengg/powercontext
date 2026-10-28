"""上下文构建：任务描述 → seekdb 混合检索 → 结构化开发上下文（含来源与状态）。

输出四块内容，与验收项一一对应：
1. applicable_specs   —— 本任务适用的规格条目（含原文与来源路径）；
2. code_targets       —— 需要修改的代码文件/符号（含片段，来自当前工作副本）；
3. verification_tests —— 用于功能与兼容性验证的测试（含用例名）；
4. task_state         —— 已完成/待办/已有验证结果（来自 PowerContext，而非本地缓存）。

检索完全由 seekdb 决定命中内容：规格更新并重新摄取后，命中的即更新后的条目。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sdd_context.seekstore import SeekStore
from sdd_context.state import PowerContextState
from sdd_context.taskrecord import TaskRecord

_CODE_REF_RE = re.compile(r"(src/[\w/.\-]+\.py)::(\w+)")
_FILE_REF_RE = re.compile(r"(?:src|tests)/[\w/.\-]+\.py")
MAX_CODE_CHARS = 6000
MAX_TEST_CHARS = 4000


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def build_context(
    project_dir: Path,
    data_dir: Path,
    task_text: str,
    task_id: str | None = None,
    state: PowerContextState | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    store = SeekStore(Path(data_dir))
    query = _norm(task_text)
    retrieval_log: list[dict[str, Any]] = []

    spec_hits, spec_log = store.hybrid("spec", query, top_k)
    code_hits, code_log = store.hybrid("code", query, top_k)
    test_hits, test_log = store.hybrid("test", query, top_k)
    retrieval_log.extend([spec_log, code_log, test_log])

    applicable_specs = []
    seen_specs: set[str] = set()
    for hit in spec_hits:
        metadata = hit["metadata"]
        req_id = metadata.get("req_id", "")
        if not req_id or req_id == "(header)":
            continue
        source = project_dir / metadata["source"]
        if not source.exists():
            continue
        key = f"{metadata['source']}#{req_id}"
        if key in seen_specs:
            continue
        seen_specs.add(key)
        applicable_specs.append(
            {
                "req_id": req_id,
                "title": metadata.get("title", ""),
                "source": metadata["source"],
                "sha": metadata.get("sha", ""),
                "text": hit["document"],
            }
        )

    # 同文档扩展：命中某规格文件后，把该文件的全部条目并入（同一规格文档通常整体适用）。
    for hit_file in dict.fromkeys(spec["source"] for spec in applicable_specs):
        existing_ids = {spec["req_id"] for spec in applicable_specs if spec["source"] == hit_file}
        for row in store.fetch_by_source("spec", hit_file):
            req_id = row["metadata"].get("req_id", "")
            if not req_id or req_id == "(header)" or req_id in existing_ids:
                continue
            source_path = project_dir / hit_file
            if not source_path.exists():
                continue
            applicable_specs.append(
                {
                    "req_id": req_id,
                    "title": row["metadata"].get("title", ""),
                    "source": hit_file,
                    "sha": row["metadata"].get("sha", ""),
                    "text": row["document"],
                    "origin": "same-spec-file",
                }
            )
            retrieval_log.append({"engine": "seekdb.get", "where": {"kind": "spec", "source": hit_file}, "expanded": req_id})

    # 规格条目里声明的“关联代码/验证”用于精确定位需要修改的文件与测试。
    ref_files: dict[str, str] = {}  # path -> origin
    for spec in applicable_specs:
        for path, symbol in _CODE_REF_RE.findall(spec["text"]):
            ref_files[path] = f"spec:{spec['req_id']}"
        for path in _FILE_REF_RE.findall(spec["text"]):
            if path.startswith("tests/"):
                ref_files.setdefault(path, f"spec:{spec['req_id']}")

    code_targets: list[dict[str, Any]] = []
    seen_code: set[str] = set()
    for hit in code_hits:
        metadata = hit["metadata"]
        path = metadata["source"]
        if path in seen_code:
            continue
        seen_code.add(path)
        symbols = [symbol for symbol in metadata.get("symbols", "").split(",") if symbol]
        entry = {"path": path, "indexed_symbols": symbols, "origin": "seekdb:code"}
        _attach_current_content(project_dir, path, entry, MAX_CODE_CHARS)
        code_targets.append(entry)
    for path, origin in ref_files.items():
        if not path.startswith("src/") or path in seen_code:
            continue
        seen_code.add(path)
        full = project_dir / path
        if not full.exists():
            continue
        from sdd_context.ingest import _py_symbols

        entry = {
            "path": path,
            "indexed_symbols": _py_symbols(full.read_text(encoding="utf-8")),
            "origin": origin,
        }
        _attach_current_content(project_dir, path, entry, MAX_CODE_CHARS)
        code_targets.append(entry)

    verification_tests: list[dict[str, Any]] = []
    seen_test: set[str] = set()
    for hit in test_hits:
        metadata = hit["metadata"]
        path = metadata["source"]
        if path in seen_test:
            continue
        seen_test.add(path)
        names = [symbol for symbol in metadata.get("symbols", "").split(",") if symbol.startswith("test_")]
        entry = {"path": path, "cases": names, "origin": "seekdb:test"}
        _attach_current_content(project_dir, path, entry, MAX_TEST_CHARS)
        verification_tests.append(entry)
    for path, origin in ref_files.items():
        if not path.startswith("tests/") or path in seen_test:
            continue
        seen_test.add(path)
        full = project_dir / path
        if not full.exists():
            continue
        from sdd_context.ingest import _py_symbols

        names = [symbol for symbol in _py_symbols(full.read_text(encoding="utf-8")) if symbol.startswith("test_")]
        entry = {"path": path, "cases": names, "origin": origin}
        _attach_current_content(project_dir, path, entry, MAX_TEST_CHARS)
        verification_tests.append(entry)

    task_state = _read_task_state(task_id, state)
    context = {
        "task": {"description": task_text, "task_id": task_id},
        "applicable_specs": applicable_specs,
        "code_targets": code_targets,
        "verification_tests": verification_tests,
        "task_state": task_state,
        "retrieval": {"engine": "seekdb", "db_path": str(store.db_path), "queries": retrieval_log},
        "source_count_in_seekdb": store.count(),
    }
    context["provenance"] = check_provenance(context, project_dir)
    return context


def _attach_current_content(project_dir: Path, rel: str, entry: dict[str, Any], limit: int) -> None:
    """片段内容以工作副本当前文件为准（来源真实存在；更新后重新摄取即生效）。"""
    path = project_dir / rel
    if not path.exists():
        entry["content"] = None
        entry["note"] = "indexed but missing on disk"
        return
    text = path.read_text(encoding="utf-8")
    entry["file_sha256"] = SeekStore.content_sha(text)
    entry["content"] = text[:limit]
    entry["truncated"] = len(text) > limit


def _read_task_state(task_id: str | None, state: PowerContextState | None) -> dict[str, Any]:
    if not task_id:
        return {"available": False, "reason": "no task_id supplied"}
    if state is None:
        return {"available": False, "reason": "PowerContext not configured"}
    try:
        record: TaskRecord | None = state.latest(task_id)
    except Exception as error:  # 连接失败要可见，不静默吞掉
        return {"available": False, "reason": f"PowerContext unavailable: {error!r}"}
    if record is None:
        return {"available": True, "records_found": 0, "done": [], "todo": [], "results": {}, "note": "空状态：尚无该任务记录"}
    return {
        "available": True,
        "records_found": len(state.search(task_id)),
        "phase": record.phase,
        "done": record.done,
        "todo": record.todo,
        "results": record.results,
        "updated_at": record.updated_at,
        "scope_id": state.scope_id,
    }


def check_provenance(context: dict[str, Any], project_dir: Path) -> dict[str, Any]:
    """输出中的来源必须真实存在：逐条核对文件与规格编号。"""
    missing: list[str] = []
    checked = 0
    for spec in context["applicable_specs"]:
        checked += 1
        path = project_dir / spec["source"]
        if not path.exists() or f"## {spec['req_id']}" not in path.read_text(encoding="utf-8"):
            missing.append(f"{spec['source']}#{spec['req_id']}")
    for entry in context["code_targets"] + context["verification_tests"]:
        checked += 1
        if not (project_dir / entry["path"]).exists():
            missing.append(entry["path"])
    return {"checked": checked, "missing": missing, "all_sources_exist": not missing}


def render_markdown(context: dict[str, Any]) -> str:
    """人类可读渲染：作为提交给 MiniMax 的开发上下文正文。"""
    lines = [f"# 开发上下文（任务 {context['task'].get('task_id') or '-'}）", ""]
    lines.append("## 任务")
    lines.append(context["task"]["description"].strip())
    lines.append("\n## 适用规格条目")
    if not context["applicable_specs"]:
        lines.append("（未命中）")
    for spec in context["applicable_specs"]:
        lines.append(f"### {spec['req_id']} {spec['title']}")
        lines.append(f"来源：{spec['source']}")
        lines.append(spec["text"].strip())
        lines.append("")
    lines.append("## 需要修改/相关的代码")
    for entry in context["code_targets"]:
        lines.append(f"### {entry['path']}（来源 {entry['origin']}）")
        if entry.get("content"):
            lines.append("```python")
            lines.append(entry["content"].rstrip())
            lines.append("```")
        lines.append("")
    lines.append("## 验证测试")
    for entry in context["verification_tests"]:
        lines.append(f"### {entry['path']}（来源 {entry['origin']}）")
        lines.append("用例：" + ", ".join(entry.get("cases", [])))
        if entry.get("content"):
            lines.append("```python")
            lines.append(entry["content"].rstrip())
            lines.append("```")
        lines.append("")
    state_block = context["task_state"]
    lines.append("## 任务状态（来自 PowerContext）")
    if state_block.get("available"):
        lines.append(f"- 阶段：{state_block.get('phase', '-')}")
        lines.append("- 已完成：" + ("；".join(state_block.get("done", [])) or "（空）"))
        lines.append("- 待办：" + ("；".join(state_block.get("todo", [])) or "（空）"))
        if state_block.get("results"):
            lines.append(f"- 已有验证结果：{state_block['results']}")
    else:
        lines.append(f"- 不可用：{state_block.get('reason')}")
    lines.append("\n## 来源核验")
    provenance = context["provenance"]
    lines.append(f"检查 {provenance['checked']} 条来源，缺失 {len(provenance['missing'])} 条：{provenance['missing'] or '无'}")
    return "\n".join(lines)
