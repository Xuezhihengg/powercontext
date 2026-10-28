#!/usr/bin/env bash
# 停止 PowerContext Server（数据保留在 .pcserver/home，重启后可继续读取任务状态）。
set -euo pipefail
cd "$(dirname "$0")/.."
PID_FILE=.pcserver/server.pid
if [[ -f ${PID_FILE} ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
  kill "$(cat "${PID_FILE}")" 2>/dev/null || true
  sleep 1
  kill -0 "$(cat "${PID_FILE}")" 2>/dev/null && kill -9 "$(cat "${PID_FILE}")" 2>/dev/null || true
  rm -f "${PID_FILE}"
  echo "PowerContext Server 已停止（任务状态保留在 .pcserver/home）"
else
  echo "没有由本脚本记录的 Server 进程（${PID_FILE} 不存在）"
fi
