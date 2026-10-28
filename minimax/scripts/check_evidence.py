#!/usr/bin/env python3
"""按题面 6 项必做验收，机械核对 evidence/ 是否成立（只读，不改任何文件）。

用法：
    python3 scripts/check_evidence.py [evidence_dir]   # 默认 evidence
    python3 scripts/check_evidence.py evidence demo_project
退出码：0 全部通过；1 存在未通过项（逐项打印原因）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ENVIRONMENT_ERRORS = ("ImportError", "ModuleNotFoundError", "No module named", "error: collected 0", "fixture '")


def load(evidence: Path, name: str):
    path = evidence / name
    if not path.exists():
        return None, f"缺少 {name}"
    try:
        return (json.loads(path.read_text(encoding="utf-8")), None) if path.suffix == ".json" else (path.read_text(encoding="utf-8"), None)
    except Exception as error:  # noqa: BLE001
        return None, f"{name} 解析失败：{error}"


def specs_of(data) -> set[str]:
    return {item["req_id"] for item in data.get("applicable_specs", [])}


def suite(report, needle: str):
    for item in report.get("suites", []):
        if needle in item["suite"]:
            return item
    return {}


def main() -> int:
    evidence = Path(sys.argv[1] if len(sys.argv) > 1 else "evidence")
    project = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("demo_project")
    results: list[tuple[str, bool, str]] = []

    def check(item: str, ok: bool, detail: str = "") -> None:
        results.append((item, ok, detail))

    transcript, err = load(evidence, "run_transcript.log")
    check("① 能够运行：存在完整运行记录", bool(transcript) and err is None, err or "")
    if transcript:
        check("① 能够运行：流程结束时异常步骤数为 0", "异常步骤数：0" in transcript,
              "未找到「异常步骤数：0」，说明 run_demo.sh 有非预期失败步骤")

    run, err = load(evidence, "step8_minimax_run.json")
    check("② MiniMax 实际参与：存在 step8 调用记录", run is not None, err or "")
    if run:
        endpoint = str(run.get("endpoint", ""))
        remote = all(token not in endpoint for token in ("127.0.0.1", "localhost", "0.0.0.0"))
        check("② MiniMax 实际参与：请求发往 MiniMax 官方服务（非本地假端点）", remote and any(token in endpoint for token in ("minimaxi.com", "minimax.io")),
              f"endpoint={endpoint}；若为本地 stub，请用真实 Key 重跑")
        check("② MiniMax 实际参与：服务端返回 usage（真实 token 计量）", bool(run.get("usage")), f"usage={run.get('usage')}")
        check("② MiniMax 实际参与：保存了送模型的完整上下文", len(str(run.get("context_markdown", ""))) > 500,
              "context_markdown 过短")
        check("② MiniMax 实际参与：保存了模型原始输出", len(str(run.get("raw_model_output", ""))) > 100, "raw_model_output 过短")
        changed = [item for item in run.get("apply_result", {}).get("changed", []) if item.get("status") == "modified"]
        check("② MiniMax 实际参与：模型改动落到代码并生成 diff", bool(changed) and bool(run.get("apply_result", {}).get("diff")),
              "apply_result.changed 无 modified 项或 diff 为空")
        diff_text, err = load(evidence, "step8_code_diff.patch")
        check("② MiniMax 实际参与：diff 文件存在且非空", bool(diff_text), err or "")
        for item in changed:
            rel = item["path"]
            after, before_snap = evidence / "code_after" / rel, evidence / "code_before" / rel
            if after.exists() and project.exists():
                current = project / rel
                text = current.read_text(encoding="utf-8") if current.exists() else None
                same = text is not None and text == after.read_text(encoding="utf-8")
                # 工作区也可能已被 scripts/reset.sh 恢复到改前基线：此时改后代码由 step9_code_after.tar.gz 交付。
                reverted = bool(before_snap.exists()) and text == before_snap.read_text(encoding="utf-8")
                archived = reverted and _tar_matches(evidence, project, rel)
                detail = ("工作区即改后代码" if same
                          else "工作区为改前基线（reset.sh 之后），改后代码见 evidence/step9_code_after.tar.gz" if archived
                          else f"工作区 {current} 既不等于 code_after/{rel}，也不等于 code_before/{rel}；"
                               "请重跑 bash scripts/run_demo.sh，或按 README 1.1 恢复提交态")
                check(f"② MiniMax 实际参与：改后代码可核对（工作区或改后归档，{rel}）", same or archived, detail)

    before, err = load(evidence, "step3_verify_before.json")
    ctx1, err2 = load(evidence, "step4_context_specv1.json")
    ingest2, err3 = load(evidence, "step5_ingest_specv2.json")
    ctx2, err4 = load(evidence, "step6_context_specv2.json")
    check("③ 上下文正确：step4/5/6 证据齐备", all(x is not None for x in (ctx1, ingest2, ctx2)), " | ".join(filter(None, [err2, err3, err4])))
    if ctx1 is not None and ctx2 is not None and ingest2 is not None:
        check("③ 上下文正确：v1 上下文不含未发布的 ORD-004/ORD-005", not ({"ORD-004", "ORD-005"} & specs_of(ctx1)),
              f"v1 命中 {sorted(specs_of(ctx1))}")
        check("③ 上下文正确：规格更新重新导入后出现 ORD-004/ORD-005", {"ORD-004", "ORD-005"} <= specs_of(ctx2),
              f"v2 命中 {sorted(specs_of(ctx2))}（ingest={ {k: ingest2[k] for k in ('added', 'updated', 'unchanged')} }）")
        required = {"ORD-001", "ORD-002", "ORD-003", "ORD-CORE-003"}
        check("③ 上下文正确：既有规格在 v2 后仍作为约束保留", required <= specs_of(ctx2), f"缺少 {sorted(required - specs_of(ctx2))}")
        for name, data in (("step4", ctx1), ("step6", ctx2)):
            prov = data.get("provenance", {})
            check(f"③ 上下文正确：{name} 来源全部可核对", prov.get("all_sources_exist") is True, f"missing={prov.get('missing')}")
        targets = {item["path"] for item in ctx2.get("code_targets", [])}
        tests = {item["path"] for item in ctx2.get("verification_tests", [])}
        check("③ 上下文正确：包含需修改的代码来源", "src/order_service/service.py" in targets, f"code_targets={sorted(targets)}")
        check("③ 上下文正确：包含目标与回归测试来源",
              {"tests/test_order_filter_target.py", "tests/test_orders_regression.py"} <= tests, f"verification_tests={sorted(tests)}")

    init, err_init = load(evidence, "step2_init.json")
    db_path = Path((init or {}).get("db_path", "")) if init else Path("")
    snap, _ = load(evidence, "step12_seekdb_dir.txt")
    live = _db_nonempty(db_path)
    snap_ok = bool(snap) and "seekdb.db" in snap and _snap_has_files(snap)
    # .sdddata/ 是运行期数据（嵌入式 seekdb 实例可达数百 MB，被 minimax/.gitignore 忽略，reset.sh 也会清空）。
    # 因此「目录当前存在且非空」或「run_demo.sh step12b 固化的物理快照」任一成立即认定数据库真实存在。
    check("④ 数据库实际参与：seekdb 数据目录/文件存在且非空（或已固化为 step12_seekdb_dir.txt 快照）",
          live or snap_ok,
          err_init or (f"db_path={db_path} 当前不存在（相对路径按当前工作目录解析），"
                       "且 evidence/step12_seekdb_dir.txt 缺失或未记录非零体积的数据文件；重跑 run_demo.sh 即可生成"))
    if ctx2 is not None:
        engines = {q.get("engine") for q in ctx2.get("retrieval", {}).get("queries", [])}
        check("④ 数据库实际参与：上下文条目来自 seekdb 检索结果", "seekdb.hybrid_search" in engines, f"engines={sorted(e for e in engines if e)}")
        check("④ 数据库实际参与：seekdb 中确有资料块", ctx2.get("source_count_in_seekdb", 0) > 0, f"count={ctx2.get('source_count_in_seekdb')}")
    for kind in ("spec", "code", "test"):
        data, err5 = load(evidence, f"step12_dbq_{kind}.json")
        ids = [hit["id"] for hit in (data or {}).get("hits", [])] if data else []
        check(f"④ 数据库实际参与：dbq {kind} 查询有命中", bool(ids), err5 or f"hits={ids}")

    st_before, _ = load(evidence, "step1_state_show_before.json")
    st_planned, err6 = load(evidence, "step7_state_planned.json")
    st_verified, err7 = load(evidence, "step10_state_verified.json")
    st_after, err8 = load(evidence, "step11_state_show_after.json")
    ctx_final, err9 = load(evidence, "step11_context_final.json")
    check("⑤ 状态能够复用：step7/10/11 证据齐备", all(x is not None for x in (st_planned, st_verified, st_after, ctx_final)),
          " | ".join(filter(None, [err6, err7, err8, err9])))
    if st_before is not None:
        check("⑤ 状态能够复用：起步为空状态（无 T-001 记录）", st_before.get("latest") is None, f"latest={st_before.get('latest')}")
    if st_planned is not None and st_verified is not None:
        check("⑤ 状态能够复用：两个阶段的状态均已写入 PowerContext",
              st_planned.get("status") == "saved" and st_verified.get("status") == "saved"
              and st_planned.get("record", {}).get("phase") == "planned" and st_verified.get("record", {}).get("phase") == "verified",
              f"planned={st_planned.get('record', {}).get('phase')} verified={st_verified.get('record', {}).get('phase')}")
        check("⑤ 状态能够复用：Scope 一致（跨进程同一存储）", st_planned.get("scope_id") == st_verified.get("scope_id") == (st_after or {}).get("scope_id"),
              f"{st_planned.get('scope_id')} / {st_verified.get('scope_id')} / {(st_after or {}).get('scope_id')}")
    if st_after is not None:
        latest = st_after.get("latest") or {}
        check("⑤ 状态能够复用：重启 Server 后新进程读到最新状态",
              latest.get("phase") == "verified" and bool(latest.get("done")), f"latest={latest}")
    if ctx_final is not None:
        state_block = ctx_final.get("task_state", {})
        check("⑤ 状态能够复用：读到的状态被用于后续上下文",
              state_block.get("records_found", 0) > 0 and bool(state_block.get("done")), f"task_state={ {k: state_block.get(k) for k in ('available', 'records_found', 'phase')} }")
        md, _ = load(evidence, "step11_context_final.md")
        check("⑤ 状态能够复用：上下文正文含「任务状态（来自 PowerContext）」段", bool(md) and "任务状态（来自 PowerContext）" in md, "")

    after, err10 = load(evidence, "step9_verify_after.json")
    check("⑥ 代码修改有效：step3/step9 验证报告齐备", before is not None and after is not None, err10 or "")
    if before is not None and after is not None:
        t_before, r_before = suite(before, "test_order_filter_target"), suite(before, "test_orders_regression")
        t_after, r_after = suite(after, "test_order_filter_target"), suite(after, "test_orders_regression")
        check("⑥ 代码修改有效：修改前目标测试功能性失败", t_before.get("exit_code", 0) != 0, f"exit={t_before.get('exit_code')}")
        output = t_before.get("output", "")
        check("⑥ 代码修改有效：失败不是环境错误", not any(token in output for token in ENVIRONMENT_ERRORS) and ("failed" in output),
              f"输出含环境错误特征或没有失败用例：{output[-200:]}")
        check("⑥ 代码修改有效：修改前回归测试全过", r_before.get("exit_code") == 0, f"exit={r_before.get('exit_code')}")
        check("⑥ 代码修改有效：修改后目标测试全过", t_after.get("exit_code") == 0, f"exit={t_after.get('exit_code')}")
        check("⑥ 代码修改有效：修改后回归测试全过", r_after.get("exit_code") == 0, f"exit={r_after.get('exit_code')}")
        hashes_before = {suite_id["suite"]: suite_id["file_sha256"] for suite_id in before["suites"]}
        hashes_after = {suite_id["suite"]: suite_id["file_sha256"] for suite_id in after["suites"]}
        check("⑥ 代码修改有效：测试文件前后未被修改", hashes_before == hashes_after, f"{hashes_before} != {hashes_after}")

    width = max(len(item) for item, _, _ in results)
    failures = 0
    for item, ok, detail in results:
        if ok:
            print(f"  PASS  {item}")
        else:
            failures += 1
            print(f"  FAIL  {item}\n        → {detail}")
    print(f"\n合计 {len(results)} 项检查，未通过 {failures} 项。")
    return 1 if failures else 0


def _db_nonempty(path: Path) -> bool:
    """嵌入式 seekdb 的 db_path 可能是目录（内含 tablet/索引文件）或单文件。"""
    if not path or not str(path):
        return False
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(item.is_file() and item.stat().st_size > 0 for item in path.rglob("*"))
    return False


def _snap_has_files(snapshot_text: str) -> bool:
    """step12_seekdb_dir.txt 里确有 seekdb 数据文件（文件数 > 0 且有非零体积条目）。"""
    counts = [int(line) for line in snapshot_text.splitlines() if line.strip().isdigit()]
    sized = [int(line.split("\t")[0]) for line in snapshot_text.splitlines() if "\t" in line and line.split("\t")[0].strip().isdigit()]
    return bool(counts) and max(counts) > 0 and bool(sized) and max(sized) > 0


def _tar_matches(evidence: Path, project: Path, rel: str) -> bool:
    import tarfile

    tar = evidence / "step9_code_after.tar.gz"
    if not tar.exists():
        return False
    with tarfile.open(tar) as handle:
        member = f"demo_project/{rel}"
        if member not in handle.getnames():
            return False
        text = handle.extractfile(member).read().decode("utf-8")
    after = (evidence / "code_after" / rel).read_text(encoding="utf-8")
    return text == after


if __name__ == "__main__":
    raise SystemExit(main())
