#!/usr/bin/env bash
# 公共函数：激活环境、恢复初始业务工程（tar 快照，不依赖 git 状态）。
# 注意：这里故意不开 set -e —— 本文件会被 run_demo.sh 等脚本 source，
# 失败步骤的退出码需要由调用方自己判断（例如“修改前测试必须失败”）。
set -uo pipefail

PC_HOME="${PWD}/.pcserver/home"

activate_env() {
  if [[ -x .venv/bin/python ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
  fi
  export PATH="${HOME}/.local/bin:${PATH}"
  export POWERCONTEXT_URL="${POWERCONTEXT_URL:-http://127.0.0.1:18081}"
  # PowerContext 的全部本地数据（任务状态库/seekdb 索引/调度库）放在作品目录内，
  # 便于演示“从空状态起步”，也不会污染 ~/.local/share/powercontext。
  export POWERCONTEXT_HOME="${POWERCONTEXT_HOME:-$(pwd)/.pcserver/home}"
}

restore_pristine_demo_project() {
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  if [[ ! -f "${root}/samples/pristine/demo_project.tar.gz" ]]; then
    echo "缺少初始快照 samples/pristine/demo_project.tar.gz" >&2
    exit 1
  fi
  rm -rf "${root}/demo_project"
  tar -xzf "${root}/samples/pristine/demo_project.tar.gz" -C "${root}"
  echo "demo_project 已从初始快照恢复。"
}

restore_committed_demo_project() {
  # 把业务工程恢复到「仓库提交态」= step8 由 MiniMax 改完之后的版本（规格 v2 + 过滤实现）。
  # 用途：无 MiniMax 密钥时跑过 run_demo.sh/reset.sh 之后，工作区会停在改前基线（v1），
  #       此时执行测试会得到「6 failed」；用本函数一键还原成提交态（14 passed），
  #       保证评审在任意时刻直接跑 demo_project 的测试都与其看到的一致。
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  if [[ ! -f "${root}/samples/committed/demo_project.tar.gz" ]]; then
    echo "缺少提交态快照 samples/committed/demo_project.tar.gz" >&2
    return 1
  fi
  rm -rf "${root}/demo_project"
  tar -xzf "${root}/samples/committed/demo_project.tar.gz" -C "${root}"
  echo "demo_project 已恢复到提交态（MiniMax 改后版本）。"
}
