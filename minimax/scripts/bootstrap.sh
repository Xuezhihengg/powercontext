#!/usr/bin/env bash
# 一键创建运行环境（Python 3.11+，推荐 uv）。产物：.venv/ 与可执行 sddctx。
set -euo pipefail
cd "$(dirname "$0")/.."

PY_VERSION="${PYTHON_VERSION:-3.12}"
if command -v uv >/dev/null 2>&1; then
  uv venv .venv --python "$PY_VERSION"
  uv pip install --python .venv/bin/python "pyseekdb==1.4.0.post1" "httpx>=0.27" "pytest>=8"
  uv pip install --python .venv/bin/python -e .
  uv tool install --force "powercontext[cli,server]==1.4.1" || pip install --python .venv/bin/python "powercontext[cli,server]==1.4.1"
else
  python3 -m venv .venv
  .venv/bin/pip install "pyseekdb==1.4.0.post1" "httpx>=0.27" "pytest>=8" "powercontext[cli,server]==1.4.1"
  .venv/bin/pip install -e .
fi
echo "环境就绪。激活：source .venv/bin/activate && export PATH=\"$HOME/.local/bin:\$PATH\"  # uv tool 安装时 powercontext 在 ~/.local/bin"
