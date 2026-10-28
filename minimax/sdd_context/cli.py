"""sddctx 命令行入口（上下文模块的统一调用入口）。

输入输出约定见 README.md「调用入口」一节；每个子命令都返回结构化 JSON 证据。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from sdd_context import __version__

DEFAULT_PC_URL = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:18081")
DEFAULT_TARGET = "tests/test_order_filter_target.py"
DEFAULT_REGRESSION = ["tests/test_orders_regression.py"]


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _emit(data: dict[str, Any], out: Path | None, quiet: bool) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if out is not None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"[sddctx] 写入 {out}")
    if not quiet:
        print(text)


def _read_task(args: argparse.Namespace) -> tuple[str, str]:
    if getattr(args, "task_file", None):
        content = Path(args.task_file).read_text(encoding="utf-8")
        meta = _parse_task_meta(content)
        return meta.get("task_id", args.task_id or "T-001"), meta.get("description", content)
    if args.task:
        return args.task_id or "T-001", args.task
    raise SystemExit("必须提供 --task 或 --task-file")


def _parse_task_meta(content: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    lines = content.splitlines()
    description_lines: list[str] = []
    mode = None
    for line in lines:
        if line.startswith("# "):
            meta.setdefault("title", line[2:].strip())
            continue
        lowered = line.lower().strip()
        if lowered.startswith("task_id:"):
            meta["task_id"] = line.split(":", 1)[1].strip()
            continue
        if lowered.startswith("description:"):
            mode = "description"
            rest = line.split(":", 1)[1].strip().lstrip("|").strip()
            if rest:
                description_lines.append(rest)
            continue
        if mode == "description":
            description_lines.append(line.strip())
    meta["description"] = " ".join(part for part in description_lines if part).strip() or content
    return meta


def cmd_init(args: argparse.Namespace) -> int:
    from sdd_context.seekstore import SeekStore

    store = SeekStore(Path(args.data_dir))
    _emit({"status": "ok", "data_dir": args.data_dir, "db_path": str(store.db_path), "collection": "eng_docs", "docs": store.count()}, args.out, args.quiet)
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from sdd_context.ingest import ingest

    stats = ingest(Path(args.project), Path(args.data_dir))
    stats["status"] = "ok"
    _emit(stats, args.out, args.quiet)
    return 0


def _build(args: argparse.Namespace):
    from sdd_context.context_builder import build_context
    from sdd_context.state import PowerContextState

    task_id, task_text = _read_task(args)
    state = None
    if not args.no_state:
        state = PowerContextState(base_url=args.pc_url)
    context = build_context(
        project_dir=Path(args.project),
        data_dir=Path(args.data_dir),
        task_text=task_text,
        task_id=task_id,
        state=state,
        top_k=args.top_k,
    )
    if state is not None:
        state.close()
    return task_id, context


def cmd_context(args: argparse.Namespace) -> int:
    from sdd_context.context_builder import render_markdown

    task_id, context = _build(args)
    context["task"]["task_id"] = task_id
    _emit(context, args.out, args.quiet)
    if args.markdown_out:
        Path(args.markdown_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown_out).write_text(render_markdown(context), encoding="utf-8")
        print(f"[sddctx] 写入 {args.markdown_out}")
    if not context["provenance"]["all_sources_exist"]:
        print("[sddctx] 警告：存在无法核对的来源！", file=sys.stderr)
        return 4
    return 0


def cmd_dbq(args: argparse.Namespace) -> int:
    from sdd_context.seekstore import SeekStore

    store = SeekStore(Path(args.data_dir))
    hits, log = store.hybrid(args.kind, args.text, args.top_k)
    _emit({"query": log, "hits": [{"id": hit["id"], "metadata": hit["metadata"]} for hit in hits]}, args.out, args.quiet)
    return 0


def cmd_patch(args: argparse.Namespace) -> int:
    from sdd_context.context_builder import render_markdown
    from sdd_context.minimax_client import generate_change
    from sdd_context.patcher import apply_change

    task_id, context = _build(args)
    allowed = {entry["path"] for entry in context["code_targets"]}
    run = generate_change(context, user_instruction=args.instruction)
    result = apply_change(Path(args.project), run["parsed"], Path(args.data_dir), allowed_paths=allowed, dry_run=args.dry_run)
    record = {
        "task_id": task_id,
        "model": run["request_log"]["model"],
        "endpoint": run["request_log"]["endpoint"],
        "context_markdown": run["request_log"]["context_markdown"],
        "raw_model_output": run["raw_response"],
        "apply_result": {**result, "changed": [{**item, "diff": item.get("diff", "")[:200] + "…" if len(item.get("diff", "")) > 200 else item.get("diff", "")} for item in result["changed"]]},
        "usage": run["request_log"].get("usage"),
    }
    _emit(record, args.out, args.quiet)
    if args.diff_out and result["diff"]:
        Path(args.diff_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.diff_out).write_text(result["diff"], encoding="utf-8")
        print(f"[sddctx] 写入 {args.diff_out}")
    return 0 if result["changed"] else 5


def cmd_verify(args: argparse.Namespace) -> int:
    from sdd_context.verify import run_all

    report = run_all(Path(args.project), args.target, args.regression)
    out_dir = Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        for suite in report["suites"]:
            log = out_dir / f"pytest_{args.label}_{Path(suite['suite']).stem}.log"
            log.write_text(f"$ {suite['command']}\n(退出码 {suite['exit_code']})\n\n{suite['output']}", encoding="utf-8")
            print(f"[sddctx] 写入 {log}")
        (out_dir / f"verify_{args.label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _emit(report, args.out, args.quiet)
    return 0 if report["all_passed"] else 1


def cmd_state_save(args: argparse.Namespace) -> int:
    from sdd_context.state import PowerContextState
    from sdd_context.taskrecord import TaskRecord

    task_id, task_text = _read_task(args)
    record = TaskRecord(
        task_id=task_id,
        title=args.title or "",
        phase=args.phase,
        done=_split(args.done),
        todo=_split(args.todo),
        results=_load_json(args.results_file),
        notes=args.notes or "",
    )
    record.touch()
    state = PowerContextState(base_url=args.pc_url, scope_id=args.scope_id)
    outcome = state.save(record)
    state.close()
    outcome["record"] = json.loads(record.to_text())
    _emit({"status": "saved", **outcome}, args.out, args.quiet)
    return 0


def cmd_state_show(args: argparse.Namespace) -> int:
    from sdd_context.state import PowerContextState

    state = PowerContextState(base_url=args.pc_url, scope_id=args.scope_id)
    record = state.latest(args.task_id)
    audit = state.audit_dump()
    state.close()
    payload = {
        "task_id": args.task_id,
        "scope_id": audit["scope_id"],
        "latest": json.loads(record.to_text()) if record else None,
        "scope_task_state_entries": audit["entries"],
    }
    _emit(payload, args.out, args.quiet)
    return 0 if record else 3


def cmd_reset(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    if data_dir.exists():
        shutil.rmtree(data_dir)
    _emit({"status": "reset", "data_dir": str(data_dir), "note": "seekdb 数据与模块本地文件已清空；任务状态仍保留在 PowerContext 中"}, args.out, args.quiet)
    return 0


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.replace("；", ";").replace("，", ",").replace(",", ";").split(";") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sddctx", description=f"sdd_context SDD 上下文模块 CLI v{__version__}")
    parser.add_argument("--quiet", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, project: bool = True, data: bool = True, task: bool = True, pc: bool = True) -> None:
        if project:
            p.add_argument("--project", default="demo_project", help="业务工程根目录")
        if data:
            p.add_argument("--data-dir", default=".sdddata", help="seekdb 数据目录")
        if task:
            p.add_argument("--task", help="任务描述文本")
            p.add_argument("--task-file", help="任务描述 Markdown（含 task_id:）")
            p.add_argument("--task-id", help="任务 ID（默认取 task-file 内 task_id）")
        if pc:
            p.add_argument("--pc-url", default=DEFAULT_PC_URL, help="PowerContext Server 地址")
            p.add_argument("--scope-id", help="显式指定 PowerContext scope_id（默认自动发现/创建）")
            p.add_argument("--no-state", action="store_true", help="不读取 PowerContext 状态")
        p.add_argument("--out", type=Path, help="把结构化结果写入 JSON 文件")

    p = sub.add_parser("init", help="初始化 seekdb 数据目录")
    common(p, project=False, task=False, pc=False)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("ingest", help="导入/更新规格、代码、测试资料")
    common(p, task=False, pc=False)
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("context", help="根据任务生成开发上下文（规格/代码/测试/状态）")
    common(p)
    p.add_argument("--markdown-out", type=Path, help="同时输出人类可读 Markdown")
    p.add_argument("--top-k", type=int, default=8)
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("dbq", help="直接查询 seekdb（演示数据库实际参与检索）")
    common(p, project=False, task=False, pc=False)
    p.add_argument("--kind", choices=["spec", "code", "test"], required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--top-k", type=int, default=8)
    p.set_defaults(func=cmd_dbq)

    p = sub.add_parser("patch", help="用 MiniMax 按上下文完成代码修改")
    common(p)
    p.add_argument("--instruction", help="附加给模型的补充指令")
    p.add_argument("--dry-run", action="store_true", help="只生成不写盘")
    p.add_argument("--diff-out", type=Path, help="把统一 diff 写入文件")
    p.add_argument("--top-k", type=int, default=8)
    p.set_defaults(func=cmd_patch)

    p = sub.add_parser("verify", help="运行目标/回归测试并记录命令、退出码与代码版本")
    p.add_argument("--project", default="demo_project")
    p.add_argument("--target", default=DEFAULT_TARGET)
    p.add_argument("--regression", nargs="+", default=DEFAULT_REGRESSION)
    p.add_argument("--label", default="run")
    p.add_argument("--out-dir", type=Path, help="日志与 JSON 报告输出目录")
    p.add_argument("--out", type=Path)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("state", help="任务状态保存/回读（PowerContext）")
    state_sub = p.add_subparsers(dest="state_command", required=True)
    sp = state_sub.add_parser("save")
    common(sp, project=False, data=False)
    sp.add_argument("--title")
    sp.add_argument("--phase", required=True)
    sp.add_argument("--done", help="分号分隔的已完成事项")
    sp.add_argument("--todo", help="分号分隔的待办事项")
    sp.add_argument("--results-file", type=Path, help="附加验证结果 JSON")
    sp.add_argument("--notes")
    sp.set_defaults(func=cmd_state_save)
    sp = state_sub.add_parser("show")
    common(sp, project=False, data=False, task=False)
    sp.add_argument("--task-id", required=True)
    sp.set_defaults(func=cmd_state_show)

    p = sub.add_parser("reset", help="清空 seekdb 数据目录与本地证据草稿（不动 PowerContext）")
    common(p, project=False, task=False, pc=False)
    p.set_defaults(func=cmd_reset)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "state" and not getattr(args, "func", None):
        parser.error("state 需要 save/show 子命令")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
