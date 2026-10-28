#!/usr/bin/env bash
# 验证样例一键流程：导入 → 上下文 → 规格更新 → 上下文更新 → MiniMax 修改 → 测试验证 → 状态复用。
# 每步产物落盘到 evidence/，命令与退出码记录在 evidence/run_transcript.log（开发记录）。
# 退出码：0=全部通过（含 step13 自检）；1=有非预期失败步骤或自检 FAIL；2=缺 MINIMAX_API_KEY；70=依赖未就绪。
#
# 可覆盖环境变量：
#   EVIDENCE_DIR=evidence          证据输出目录（彩排时可指向临时目录）
#   SDD_DATA_DIR=.sdddata          seekdb 数据目录
#   FRESH_PC=1                     先清空 PowerContext 库并重启 Server（演示“空状态起步”）；FRESH_PC=0 保留现有状态
#   MINIMAX_API_KEY=...            必填（step8 真实调用 MiniMax）
#   MINIMAX_MODEL / MINIMAX_MAX_TOKENS / MINIMAX_ATTEMPTS  MiniMax 调用参数（默认 MiniMax-M3）
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source scripts/_lib.sh
activate_env

EVIDENCE_DIR="${EVIDENCE_DIR:-evidence}"
DATA_DIR="${SDD_DATA_DIR:-.sdddata}"
LOGS_DIR="${EVIDENCE_DIR}/logs"
TRANSCRIPT="${EVIDENCE_DIR}/run_transcript.log"
mkdir -p "${EVIDENCE_DIR}" "${LOGS_DIR}"
: > "${TRANSCRIPT}"
FAILED=0
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "${TRANSCRIPT}"; }

# run <cmd...>：执行并把输出与退出码写入 transcript；非零退出计入 FAILED
run() {
  say "\$ $*"
  local code=0
  "$@" >> "${TRANSCRIPT}" 2>&1 || code=$?
  say "  -> exit ${code}"
  echo "exit ${code}: $*" >> "${TRANSCRIPT}"
  if [[ ${code} -ne 0 ]]; then FAILED=$((FAILED + 1)); fi
  return ${code}
}

# run_expected_fail <cmd...>：预期失败（如“修改前目标测试必须不过”），非零退出不计入 FAILED
run_expected_fail() {
  say "\$ $*   （预期非零退出）"
  local code=0
  "$@" >> "${TRANSCRIPT}" 2>&1 || code=$?
  say "  -> exit ${code}（预期 ${code} != 0）"
  echo "expected-fail exit ${code}: $*" >> "${TRANSCRIPT}"
  if [[ ${code} -eq 0 ]]; then
    say "  !! 该步骤应当失败却成功了，验收项“修改前功能性失败”不成立"
    FAILED=$((FAILED + 1))
  fi
  return 0
}

say "== 0. 前置检查 + 重置样例数据（业务工程回到初始快照）=="
# preflight：先确认命令行依赖齐全，再清空证据目录——
# 否则一旦 sddctx/powercontext 不在 PATH（未跑 bootstrap.sh 或未激活虚拟环境），
# 后面每步都是 exit 127，而本步骤已经把上一次的 evidence/ 删掉了。
PREFLIGHT=0
for tool in sddctx powercontext python3 curl; do
  if command -v "${tool}" >/dev/null 2>&1; then
    say "  ok   ${tool} -> $(command -v "${tool}")"
  else
    say "  MISS ${tool}：请先运行 bash scripts/bootstrap.sh，并激活它创建的 .venv（见 README）"
    PREFLIGHT=1
  fi
done
if ! python3 -c "import pyseekdb, httpx, pytest" >/dev/null 2>&1; then
  say "  MISS 依赖导入失败（pyseekdb/httpx/pytest）：请运行 bash scripts/bootstrap.sh"
  PREFLIGHT=1
fi
if [[ ${PREFLIGHT} -ne 0 ]]; then
  say "!! 前置检查未通过，已中止；evidence/ 未改动。退出码 70。"
  exit 70
fi
restore_pristine_demo_project
if [[ "${DATA_DIR}" != "${EVIDENCE_DIR}" ]]; then rm -rf "${DATA_DIR}"; fi
rm -rf "${EVIDENCE_DIR}"
mkdir -p "${EVIDENCE_DIR}" "${LOGS_DIR}"
: > "${TRANSCRIPT}"

say "== 1. PowerContext Server（18081；FRESH_PC=${FRESH_PC:-1}）=="
if [[ "${FRESH_PC:-1}" == "1" ]]; then
  bash scripts/stop_server.sh >> "${TRANSCRIPT}" 2>&1 || true
  rm -rf .pcserver/home >> "${TRANSCRIPT}" 2>&1 || true
  say "  已清空 PowerContext 数据目录 .pcserver/home，演示从空状态起步"
fi
if ! curl -sf "${POWERCONTEXT_URL}/health/live" >/dev/null; then
  bash scripts/start_server.sh
  sleep 1
fi
run_expected_fail sddctx --quiet state show --task-id T-001 --out "${EVIDENCE_DIR}/step1_state_show_before.json" \
  || true
say "  （step1 预期 exit 3：空状态——PowerContext 中尚无 T-001 记录）"

say "== 2. 导入工程资料到 seekdb（规格 v1）=="
run sddctx --quiet init --data-dir "${DATA_DIR}" --out "${EVIDENCE_DIR}/step2_init.json"
run sddctx --quiet ingest --project demo_project --data-dir "${DATA_DIR}" --out "${EVIDENCE_DIR}/step2_ingest_specv1.json"

say "== 3. 修改前测试基线（目标测试因功能未实现而失败，回归测试全过）=="
run_expected_fail sddctx --quiet verify --project demo_project --label before \
  --out-dir "${LOGS_DIR}" --out "${EVIDENCE_DIR}/step3_verify_before.json"

say "== 4. v1 规格下的开发上下文（应检索不到 ORD-004/ORD-005）=="
run sddctx --quiet context --project demo_project --data-dir "${DATA_DIR}" --task-file samples/task-T001.md \
  --out "${EVIDENCE_DIR}/step4_context_specv1.json" --markdown-out "${EVIDENCE_DIR}/step4_context_specv1.md"

say "== 5. 规格更新为 v2 并重新导入（模拟 SDD 规格演进）=="
cp -f samples/spec_update/SPEC-order-query.md demo_project/specs/SPEC-order-query.md
say "\$ cp -f samples/spec_update/SPEC-order-query.md demo_project/specs/SPEC-order-query.md"
run sddctx --quiet ingest --project demo_project --data-dir "${DATA_DIR}" --out "${EVIDENCE_DIR}/step5_ingest_specv2.json"

say "== 6. 更新后的开发上下文：必须出现 ORD-004/ORD-005 =="
run sddctx --quiet context --project demo_project --data-dir "${DATA_DIR}" --task-file samples/task-T001.md \
  --out "${EVIDENCE_DIR}/step6_context_specv2.json" --markdown-out "${EVIDENCE_DIR}/step6_context_specv2.md"

say "== 7. 保存“规划阶段”任务状态到 PowerContext =="
run sddctx --quiet state save --task-file samples/task-T001.md --title "订单查询支持状态与金额下限过滤" \
  --phase planned --done "资料导入seekdb;规格v1与v2摄取;开发上下文生成" --todo "MiniMax代码修改;修改后目标与回归验证;归档证据" \
  --out "${EVIDENCE_DIR}/step7_state_planned.json"

say "== 8. MiniMax 依据上下文完成一次实际代码修改 =="
if [[ -z "${MINIMAX_API_KEY:-}" ]]; then
  say "!! 未设置 MINIMAX_API_KEY，无法执行真实 MiniMax 修改（题面硬性要求）。中止于 step8。"
  say "   已完成步骤的产物在 ${EVIDENCE_DIR}/；设置密钥后重跑本脚本即可续上 step8-12。"
  exit 2
fi
run sddctx --quiet patch --project demo_project --data-dir "${DATA_DIR}" --task-file samples/task-T001.md \
  --out "${EVIDENCE_DIR}/step8_minimax_run.json" --diff-out "${EVIDENCE_DIR}/step8_code_diff.patch"
if [[ -f "${EVIDENCE_DIR}/step8_code_diff.patch" ]]; then
  say "   代码差异：${EVIDENCE_DIR}/step8_code_diff.patch（修改前文件另存于 ${DATA_DIR}/backups/）"
fi
run python3 scripts/snapshots.py "${EVIDENCE_DIR}/step8_minimax_run.json" "${EVIDENCE_DIR}" demo_project

say "== 9. 修改后验证：目标测试 + 回归测试全部通过 =="
run sddctx --quiet verify --project demo_project --label after --out-dir "${LOGS_DIR}" \
  --out "${EVIDENCE_DIR}/step9_verify_after.json"
tar -czf "${EVIDENCE_DIR}/step9_code_after.tar.gz" -C . demo_project 2>/dev/null || true

say "== 10. 把验证结果写回 PowerContext 任务状态 =="
run sddctx --quiet state save --task-file samples/task-T001.md --title "订单查询支持状态与金额下限过滤" \
  --phase verified --done "资料导入seekdb;规格v1与v2摄取;开发上下文生成;MiniMax代码修改;目标与回归测试全部通过" \
  --todo "归档证据;提交评审" --results-file "${EVIDENCE_DIR}/step9_verify_after.json" \
  --notes "T-001 代码修改与验证完成（详见 evidence/step8-9）" \
  --out "${EVIDENCE_DIR}/step10_state_verified.json"

say "== 11. 重启上下文模块与 Server 后，新进程读取并复用任务状态 =="
bash scripts/stop_server.sh >> "${TRANSCRIPT}" 2>&1 || true
say "\$ scripts/stop_server.sh && scripts/start_server.sh（状态库不变）"
bash scripts/start_server.sh >> "${TRANSCRIPT}" 2>&1
run sddctx --quiet state show --task-id T-001 --out "${EVIDENCE_DIR}/step11_state_show_after.json"
run sddctx --quiet context --project demo_project --data-dir "${DATA_DIR}" --task-file samples/task-T001.md \
  --out "${EVIDENCE_DIR}/step11_context_final.json" --markdown-out "${EVIDENCE_DIR}/step11_context_final.md"

say "== 12. seekdb 检索演示（数据库实际参与上下文选择）=="
run sddctx --quiet dbq --data-dir "${DATA_DIR}" --kind spec --text "订单 状态 金额 过滤" --out "${EVIDENCE_DIR}/step12_dbq_spec.json"
run sddctx --quiet dbq --data-dir "${DATA_DIR}" --kind code --text "list_orders 过滤" --out "${EVIDENCE_DIR}/step12_dbq_code.json"
run sddctx --quiet dbq --data-dir "${DATA_DIR}" --kind test --text "filter status min_amount" --out "${EVIDENCE_DIR}/step12_dbq_test.json"

say "== 完成。异常步骤数：${FAILED}（step1 空状态、step3 修改前失败属预期，不计入）=="

# step13：按题面 6 项验收机械核对证据（放在汇总行之后，保证自检能读到“异常步骤数：0”）
CHECK_RC=0
say "== 13. 验收自检：python3 scripts/check_evidence.py ${EVIDENCE_DIR} demo_project =="
python3 scripts/check_evidence.py "${EVIDENCE_DIR}" demo_project >> "${TRANSCRIPT}" 2>&1 || CHECK_RC=$?
tail -3 "${TRANSCRIPT}" | sed 's/^/   /'
say "  -> check_evidence exit ${CHECK_RC}（0=6 项验收全部成立）"

say "   证据目录：${EVIDENCE_DIR}/（transcript: ${TRANSCRIPT}）"
if [[ ${CHECK_RC} -ne 0 ]]; then
  say "!! 验收自检未通过：请按上方 FAIL 行修正（例如用真实 MINIMAX_API_KEY 重跑，而非本地假端点）"
fi
exit $(( (FAILED > 0 || CHECK_RC > 0) ? 1 : 0 ))
