#!/usr/bin/env bash
# 一键创建运行环境（Python 3.11+，有 uv 用 uv，没有则退回 python3 -m venv）。
# 产物：.venv/（内含可执行 sddctx 与 powercontext，激活后直接可用）。
set -euo pipefail
cd "$(dirname "$0")/.."

PY_VERSION="${PYTHON_VERSION:-3.12}"
DEPS=("pyseekdb==1.4.0.post1" "httpx>=0.27" "pytest>=8" "powercontext[cli,server]==1.4.1")

if command -v uv >/dev/null 2>&1; then
  uv venv .venv --python "$PY_VERSION"
  uv pip install --python .venv/bin/python "${DEPS[@]}"
  uv pip install --python .venv/bin/python -e .
else
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet "${DEPS[@]}"
  .venv/bin/pip install --quiet -e .
fi

echo "== 环境就绪，已安装关键依赖版本 =="
.venv/bin/python - <<'PY'
import importlib.metadata as m
for pkg in ("pyseekdb", "powercontext", "httpx", "pytest", "minimax-sdd-context"):
    try:
        print(f"  {pkg}=={m.version(pkg)}")
    except Exception as error:
        print(f"  {pkg} 读取失败：{error}")
PY
echo "== 下一步 =="
echo "  source .venv/bin/activate          # .venv/bin 内含 sddctx 与 powercontext"
echo "  bash scripts/start_server.sh       # PowerContext Server（127.0.0.1:18081）"
echo "  export MINIMAX_API_KEY=<你的 Key> && bash scripts/run_demo.sh"
