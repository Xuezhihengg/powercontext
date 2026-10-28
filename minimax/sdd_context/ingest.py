"""资料摄取：把规格/代码/测试切块写入 seekdb，并按内容哈希增量更新。

- 规格（specs/*.md）：按 `## <编号>` 小节切块，规格编号进入 metadata。
- 代码（src/**.py）：整文件切块（120 行/块），AST 提取符号名。
- 测试（tests/**.py）：同代码切块，metadata 记录 test_* 用例名。

重复摄取时内容未变化的块跳过、变化块 upsert、消失的块删除——
因此“更新规格并重新导入”后检索结果会使用更新后的内容。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from sdd_context.seekstore import SeekStore

SPEC_SECTION_RE = re.compile(r"^##\s+(\S+)\s+(.*)$", re.MULTILINE)
CODE_CHUNK_LINES = 120


def _py_symbols(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return names


def scan_project(project_dir: Path) -> list[dict[str, Any]]:
    """把业务工程转换为待写入 seekdb 的文档块集合。"""
    project_dir = Path(project_dir)
    docs: list[dict[str, Any]] = []

    for path in sorted((project_dir / "specs").rglob("*.md")):
        rel = str(path.relative_to(project_dir))
        text = path.read_text(encoding="utf-8")
        header = text.split("##", 1)[0].strip()
        sections = SPEC_SECTION_RE.findall(text)
        if not sections:
            docs.append({"id": f"spec:{rel}#(whole)", "text": text, "metadata": {"kind": "spec", "source": rel, "req_id": ""}})
            continue
        docs.append({"id": f"spec:{rel}#(header)", "text": header, "metadata": {"kind": "spec", "source": rel, "req_id": "(header)"}})
        cursor_sections = re.split(r"(?=^##\s)", text, flags=re.MULTILINE)
        for chunk in cursor_sections:
            match = SPEC_SECTION_RE.match(chunk)
            if not match:
                continue
            docs.append(
                {
                    "id": f"spec:{rel}#{match.group(1)}",
                    "text": chunk.strip(),
                    "metadata": {"kind": "spec", "source": rel, "req_id": match.group(1), "title": match.group(2).strip()},
                }
            )

    for group, folder in (("code", "src"), ("test", "tests")):
        base = project_dir / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = str(path.relative_to(project_dir))
            source = path.read_text(encoding="utf-8")
            symbols = _py_symbols(source)
            lines = source.splitlines(keepends=True)
            for index in range(0, max(1, len(lines) // CODE_CHUNK_LINES + 1)):
                chunk = "".join(lines[index * CODE_CHUNK_LINES : (index + 1) * CODE_CHUNK_LINES])
                if not chunk.strip():
                    continue
                metadata = {
                    "kind": group,
                    "source": rel,
                    "symbols": ",".join(symbols),
                    "chunk": index,
                }
                docs.append({"id": f"{group}:{rel}#{index}", "text": chunk, "metadata": metadata})
    return docs


def ingest(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """全量扫描 + 增量写库；返回统计（供验证样例核对）。"""
    store = SeekStore(Path(data_dir))
    manifest_path = Path(data_dir) / "manifest.json"
    previous: dict[str, str] = {}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))

    docs = scan_project(project_dir)
    current: dict[str, str] = {}
    add_ids, add_docs, add_metas = [], [], []
    added = updated = unchanged = 0
    for doc in docs:
        sha = SeekStore.content_sha(doc["text"])
        current[doc["id"]] = sha
        if previous.get(doc["id"]) == sha:
            unchanged += 1
            continue
        if doc["id"] in previous:
            updated += 1
        else:
            added += 1
        metadata = dict(doc["metadata"])
        metadata["sha"] = sha
        add_ids.append(doc["id"])
        add_docs.append(doc["text"])
        add_metas.append(metadata)

    removed = [doc_id for doc_id in previous if doc_id not in current]
    store.delete(removed)
    store.upsert(add_ids, add_docs, add_metas)
    store.refresh()
    manifest_path.write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "collection": "eng_docs",
        "db_path": str(store.db_path),
        "docs_total": len(docs),
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "removed": len(removed),
        "count_in_seekdb": store.count(),
    }
