#!/usr/bin/env bash
# 重置验证样例：业务工程回到初始快照、清空 seekdb 数据目录。
#   scripts/reset.sh              只重置 demo_project + seekdb（PowerContext 状态保留，可演示复用）
#   scripts/reset.sh --pc-reset   额外清空 PowerContext 任务状态库（回到完全空状态）
#   scripts/reset.sh --committed  反向操作：把 demo_project 恢复到仓库提交态（MiniMax 改后 v2）
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source scripts/_lib.sh
activate_env
MODE="${1:-}"
if [[ "${MODE}" == "--committed" ]]; then
  restore_committed_demo_project
  echo "提示：demo_project 现为提交态，pytest tests 应 14 passed；seekdb 数据目录与 evidence/ 均未改动。"
  exit 0
fi
restore_pristine_demo_project
rm -rf "${SDD_DATA_DIR:-.sdddata}"
if [[ "${1:-}" == "--pc-reset" ]]; then
  bash scripts/stop_server.sh || true
  rm -rf .pcserver/home
  echo "已同时清空 PowerContext 任务状态（.pcserver/home）。"
fi
echo "已重置：demo_project 回到初始版本，seekdb 数据目录已清空。"
echo "下一步：bash scripts/run_demo.sh（需先 export MINIMAX_API_KEY=...）。"
