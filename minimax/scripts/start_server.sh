#!/usr/bin/env bash
# 启动 PowerContext Server（默认 127.0.0.1:18081）。
# 任务状态库等数据保存在 .pcserver/home（POWERCONTEXT_HOME），随作品目录走，删除即可回到空状态。
set -euo pipefail
cd "$(dirname "$0")/.."
PC_PORT="${POWERCONTEXT_PORT:-18081}"
mkdir -p .pcserver .pcserver/home
cat > .pcserver/powercontext.env <<ENV
POWERCONTEXT_SERVER_DASHBOARD_ENABLED=false
POWERCONTEXT_SERVER_ACCESS_MODE=disabled
ENV
if ! command -v powercontext >/dev/null 2>&1; then
  echo "未找到 powercontext 命令：请先运行 scripts/bootstrap.sh（或 uv tool install powercontext[cli,server]）" >&2
  exit 1
fi
export POWERCONTEXT_HOME="${POWERCONTEXT_HOME:-$(pwd)/.pcserver/home}"
echo "PowerContext Server: http://127.0.0.1:${PC_PORT}"
echo "  数据目录: ${POWERCONTEXT_HOME}（日志 .pcserver/server.log）"
setsid powercontext server run --host 127.0.0.1 --port "${PC_PORT}" --env-file .pcserver/powercontext.env \
  > .pcserver/server.log 2>&1 &
echo $! > .pcserver/server.pid
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PC_PORT}/health/ready" >/dev/null; then echo "  ready"; exit 0; fi
  sleep 1
done
echo "Server 未在 60s 内就绪，请查看 .pcserver/server.log" >&2
exit 1
