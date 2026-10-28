# 规有所依 —— SDD 上下文管理系统（seekdb + PowerContext + MiniMax）

OceanBase AI 数据库大赛 · MiniMax 赛题「规有所依——SDD 上下文管理系统」的参赛作品。
一句话：**规格（SDD）落到 seekdb 里可检索，任务状态落到 PowerContext 里可复用，代码修改交给 MiniMax 真实执行，每一步都用测试与证据文件可核对。**

本目录（`minimax/`）自包含：业务样例工程、上下文模块源码、一键验证脚本、验证样例文档与运行证据。

---

## 1. 目录结构

```
minimax/
├── README.md                  ← 本文件：运行说明
├── 一页技术说明.md            ← 架构 / 上下文选择流程 / 三项技术分工 / 验收映射
├── 验证样例.md                ← 评审按此逐项操作即可（T-001，12 步）
├── 技术使用记录.md            ← 开发记录 + seekdb/PowerContext/MiniMax 使用证据索引
├── pyproject.toml             ← Python 包 minimax-sdd-context，命令行入口 sddctx
├── sdd_context/               ← 上下文模块源码（12 个模块，见「一页技术说明」）
│   ├── cli.py                 ← 统一调用入口（init/ingest/context/dbq/patch/verify/state/reset）
│   ├── ingest.py              ← 规格/代码/测试切块 + 按内容哈希增量更新
│   ├── seekstore.py           ← seekdb 建库、混合检索（全文 + 向量 + RRF）、检索日志
│   ├── embedding.py           ← 确定性哈希 n-gram 向量（离线可复现，不下载模型）
│   ├── context_builder.py     ← 任务 → seekdb 检索 → 结构化开发上下文 + 来源核验
│   ├── state.py               ← PowerContext atomic-memory 状态通道（无本地状态文件）
│   ├── taskrecord.py          ← 任务状态记录（phase/done/todo/results）
│   ├── minimax_client.py      ← MiniMax chat completions 调用（OpenAI 兼容）
│   ├── patcher.py             ← 上下文白名单校验、备份、写盘、统一 diff
│   ├── verify.py              ← 运行目标/回归测试并留痕（命令、退出码、代码版本）
│   └── __main__.py            ← python -m sdd_context 等价入口
├── demo_project/              ← 被测业务工程「订单服务」。**提交态 = MiniMax 改后版本**（见下方「提交态与初始态」）
│   ├── specs/                 ← 3 份规格：SPEC-order-query（提交态为 v2，含 ORD-004/005）/ SPEC-order-core / SPEC-refund-boundary
│   ├── src/order_service/     ← models.py / repository.py / service.py
│   └── tests/                 ← test_order_filter_target.py（目标）+ test_orders_regression.py（回归）
├── samples/
│   ├── task-T001.md           ← 验证样例的任务描述
│   ├── spec_update/SPEC-order-query.md  ← 规格 v2（新增 ORD-004/ORD-005）
│   ├── pristine/demo_project.tar.gz     ← 业务工程**改前基线**（规格 v1 + 未实现过滤的 service.py）
│   └── committed/demo_project.tar.gz    ← 业务工程**提交态**（= step8 MiniMax 改后版本）的快照，供一键还原
├── scripts/
│   ├── bootstrap.sh           ← 建 .venv 并安装依赖
│   ├── start_server.sh        ← 启 PowerContext Server（127.0.0.1:18081）
│   ├── stop_server.sh         ← 停 Server（任务状态保留）
│   ├── run_demo.sh            ← 一键跑完 12 步验证样例 + step13 验收自检，产出 evidence/
│   ├── check_evidence.py      ← 按题面 6 项验收机械核对 evidence/（38 项检查）
│   ├── reset.sh               ← 业务工程回到改前基线 + 清空 seekdb（--pc-reset 连状态一起清；--committed 还原提交态）
│   └── snapshots.py           ← 由 step8 记录展开 evidence/code_before|code_after
└── evidence/                  ← 运行产物（每次 run_demo.sh 覆盖），见第 7 节
```

运行期生成的本地目录（已在 `minimax/.gitignore` 中忽略）：`.venv/`、`.sdddata/`（seekdb 数据）、`.pcserver/`（PowerContext 数据与日志）。

### 1.1 提交态与初始态（先读这段，避免误判测试结果）

题面写的是「代码结果以评审实际执行的测试为准」，所以**仓库里提交的 `demo_project/` 是 step8 由 MiniMax 改完之后的版本**（规格 v2 + 带 `status`/`min_amount` 过滤的实现）。两个状态都在仓库内交付，核对方式如下：

| 想看什么 | 命令 | 预期 |
|---|---|---|
| 改后代码（= 仓库提交态）测试全过 | `cd demo_project && python -m pytest tests -q -o addopts=` | **14 passed**（目标 6 + 回归 8） |
| 改前代码（初始基线）目标测试功能性失败 | `mkdir -p /tmp/pc_before && tar -xzf samples/pristine/demo_project.tar.gz -C /tmp/pc_before && cd /tmp/pc_before/demo_project && python -m pytest tests/test_order_filter_target.py -q -o addopts=` | **6 failed**（`TypeError: list_orders() got an unexpected keyword argument 'status'`）；同目录回归测试 **8 passed** |
| 完整复现「改前失败 → MiniMax 真实改 → 改后全过 → 自检 38 PASS」 | `export MINIMAX_API_KEY=... && bash scripts/run_demo.sh`（step0 会先 `restore_pristine_demo_project()`） | 退出码 0 |
| **没有 Key** 时试跑（保护交付物） | `bash scripts/run_demo.sh`（未设 Key） | **退出码 2，且在 step0 就中止：`evidence/` 与 `demo_project/` 一字未改**，随后 14 passed / 38 项全 PASS 都不受影响 |
| 离线演示 step1–7（不覆盖已归档证据） | `ALLOW_PARTIAL_RUN=1 bash scripts/run_demo.sh` | 退出码 2；产物写入 `evidence_partial/`，结束时自动把 `demo_project/` 还原为提交态 |
| 把仓库工作区回到改前基线 | `bash scripts/reset.sh`（不动 `evidence/`） | `demo_project/` = v1，`rm -rf .sdddata` |
| 把 `demo_project/` 还原成提交态 | `bash scripts/reset.sh --committed` | `demo_project/` = v2（MiniMax 改后），`evidence/`/`.sdddata` 不动 |

`run_demo.sh` 每次都从 `samples/pristine/` 的初始快照起步，因此**无论工作区当前是改前还是改后态，一键流程结果一致**；
「先复位工作区再动 `evidence/`」的顺序也保证了：任何中途失败（缺 Key、缺依赖、MiniMax 调用异常）都不会让已归档的那次真实运行证据消失（若全流程走到 step8 之后才失败，上一次证据还会先备份到 `.evidence_backup/<时间戳>/`，可原样还原）；`evidence/code_before/` 与 `demo_project/src/order_service/service.py` 的差异即 `evidence/step8_code_diff.patch`。

---

## 2. 环境要求

| 依赖 | 版本（本作品实测通过） | 说明 |
|---|---|---|
| Python | 3.12.3（要求 ≥ 3.11） | 系统自带即可 |
| pyseekdb | 1.4.0.post1 | 嵌入式 seekdb，读本地文件即可用，**无需单独起数据库服务** |
| powercontext | 1.4.1（extras：`cli,server`） | 提供 `powercontext server run`，任务状态存储与检索 |
| httpx | 0.28.1 | 调 PowerContext HTTP API 与 MiniMax API |
| pytest | 9.2.0 | 运行 demo_project 的目标/回归测试 |
| minimax-sdd-context | 0.1.0（本目录，editable 安装） | 提供 `sddctx` 命令 |

网络要求：只有 `sddctx patch`（MiniMax 调用）需要访问 `https://api.minimaxi.com`；其余步骤完全离线。
端口要求：默认 `127.0.0.1:18081` 给 PowerContext Server（`POWERCONTEXT_PORT` 可改），若被占用请换端口。

## 3. 快速开始（三步）

```bash
cd minimax

# ① 建环境（有 uv 用 uv，没有则自动退回 python3 -m venv）
bash scripts/bootstrap.sh                     # 装到 minimax/.venv（含 sddctx 与 powercontext）
source .venv/bin/activate
# 若你选择用 uv tool 独立安装 powercontext（落在 ~/.local/bin），补一句：
# export PATH="$HOME/.local/bin:$PATH"

# ② 启 PowerContext Server（状态库落在 minimax/.pcserver/home）
bash scripts/start_server.sh                  # 停止：bash scripts/stop_server.sh

# ③ 跑完整验证样例（12 步，产出 evidence/）
export MINIMAX_API_KEY=<你的 MiniMax Key>
bash scripts/run_demo.sh
echo "exit=$?"                               # 0 = 12 步全过 且 step13 验收自检 38 项全 PASS
# 退出码：0 全过；2 缺 MINIMAX_API_KEY；70 依赖未就绪（step0 前置自检会打印缺哪个命令）；1 有异常步骤或自检 FAIL
```

`run_demo.sh` 的 **step13 会自己核对六项验收**（`scripts/check_evidence.py`，38 项 PASS/FAIL），不需要人工读日志：

```bash
python3 scripts/check_evidence.py evidence   # 可单独执行；FAIL 行会写明缺哪个证据
```

`run_demo.sh` 结束后：

- `evidence/run_transcript.log` —— 每条命令、退出码、测试输出（开发记录主线索）
- `evidence/step*.json|md` —— 每步结构化证据
- `evidence/code_before/`、`evidence/code_after/`、`evidence/step8_code_diff.patch` —— MiniMax 修改前后代码
- `evidence/logs/pytest_{before,after}_*.log` —— 修改前/后的 pytest 原始输出

只想先看流程、暂不调用 MiniMax：`bash scripts/run_demo.sh` 会在 **step0 的前置门禁**就报错退出（exit 2），**不创建也不清空 `evidence/`**，因此仓库里已归档的真实运行证据保持原样；想看 step1–7 的离线产物，用 `ALLOW_PARTIAL_RUN=1 bash scripts/run_demo.sh`（产物写入 `evidence_partial/`，结束后 `demo_project/` 自动还原为提交态）。

## 4. 环境变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `MINIMAX_API_KEY` | 无（必填） | MiniMax 鉴权，只在运行时读取，不落盘、不写入证据 |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.com/v1` | OpenAI 兼容端点前缀 |
| `MINIMAX_MODEL` | `MiniMax-M3` | 代码修改模型。MiniMax 开放平台已于 2026 年下线 M2.x，请求旧模型名会返回 404；可下单的模型名以 `GET /v1/models` 为准 |
| `MINIMAX_MAX_TOKENS` / `MINIMAX_TIMEOUT` | `24000` / `900` | 生成上限 / 请求超时。MiniMax-M3 是「先思考再作答」的推理模型，思考与答案共用这段预算，太小会被 `finish_reason=length` 截断 |
| `MINIMAX_ATTEMPTS` / `MINIMAX_TEMPERATURE` | `2` / `0.1` | 解析失败或被截断时的自动修复重试次数 / 采样温度 |
| `POWERCONTEXT_URL` | `http://127.0.0.1:18081` | 状态通道地址（CLI 也可用 `--pc-url`） |
| `POWERCONTEXT_PORT` | `18081` | `start_server.sh` 监听端口 |
| `POWERCONTEXT_HOME` | `minimax/.pcserver/home` | PowerContext 全部本地数据目录（脚本已自动设置） |
| `SDD_DATA_DIR` | `.sdddata` | seekdb 数据目录（`seekdb.db` + `manifest.json` + `backups/`） |
| `EVIDENCE_DIR` | `evidence`（`ALLOW_PARTIAL_RUN=1` 时默认 `evidence_partial`） | 证据输出目录 |
| `ALLOW_PARTIAL_RUN` | `0` | `1` = 缺 `MINIMAX_API_KEY` 时仍允许跑到 step7 后中止（退出码 2），且不触碰 `evidence/` |
| `FRESH_PC` | `1` | `1` = 先清空 PowerContext 库，演示「从空状态起步」；`0` = 保留现有状态 |

## 5. 调用入口（模块对外接口）

统一入口 `sddctx`（等价 `python -m sdd_context`），全局开关 `--quiet` 只写文件不打印 JSON。

| 命令 | 作用 | 关键参数 | 主要输出 |
|---|---|---|---|
| `sddctx init` | 初始化 seekdb 数据目录/集合 | `--data-dir --out` | `{"status","data_dir","db_path","collection","docs"}` |
| `sddctx ingest` | 导入或增量更新工程资料 | `--project --data-dir --out` | `docs_total/added/updated/unchanged/removed/count_in_seekdb` |
| `sddctx context` | 生成开发上下文（核心能力） | `--project --data-dir --task-file --out --markdown-out --top-k [--no-state]` | `task/applicable_specs/code_targets/verification_tests/task_state/retrieval/provenance` |
| `sddctx dbq` | 直接查 seekdb（演示数据库参与检索） | `--data-dir --kind spec\|code\|test --text --top-k --out` | 命中 id + metadata + 完整查询日志 |
| `sddctx patch` | 用 MiniMax 按上下文改代码 | `--project --data-dir --task-file [--instruction] [--dry-run] --out --diff-out` | 送模型的上下文、模型原始输出与答案、`usage`/`finish_reason`/每次尝试耗时、diff、备份路径 |
| `sddctx verify` | 跑目标+回归测试并留痕 | `--project [--target] [--regression ...] --label before\|after --out-dir --out` | 每套用例的命令/退出码/代码哈希/输出 |
| `sddctx state save` | 写任务状态到 PowerContext | `--task-file --phase --done --todo --results-file --notes --out` | scope_id + 请求文本 + Server 响应 |
| `sddctx state show` | 从 PowerContext 回读最新状态 | `--task-id --out` | `scope_id/latest{phase,done,todo,results,...}` |
| `sddctx reset` | 清空 seekdb 数据目录 | `--data-dir --out` | 幂等，不动 PowerContext 状态 |

退出码约定（便于脚本判定，均已在 `run_demo.sh` 中核对）：

| 码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | `verify` 存在未通过的测试套件 |
| `2` | `run_demo.sh` 缺少 `MINIMAX_API_KEY`（step0 门禁即退出，`evidence/`/`demo_project/` 未改动；`ALLOW_PARTIAL_RUN=1` 时则停在 step8 并还原提交态） |
| `3` | `state show`：该任务在 PowerContext 中还没有记录（空状态） |
| `4` | `context`：`provenance.missing` 非空，即输出的来源无法核对 |
| `5` | `patch`：模型输出没有造成任何文件改动 |
| `70` | `run_demo.sh`：step0 前置自检发现 `sddctx`/`powercontext`/依赖不可用（此时 `evidence/` 未被改动） |

`patch` 另有硬约束：只允许写「上下文里出现的代码文件」，越界路径、新增文件、改测试/改规格一律被 `patcher.py` 拒绝。

## 6. 单独验证某一项验收（最小命令集）

```bash
cd minimax && source .venv/bin/activate && export PATH="$HOME/.local/bin:$PATH"
bash scripts/start_server.sh
bash scripts/reset.sh            # 关键：本节的命令假设从「改前基线」开始（仓库提交态是改后代码）

# 数据库实际参与：看 seekdb 里到底存了什么、查得到什么
sddctx init --data-dir .sdddata --out /tmp/init.json
sddctx ingest --project demo_project --data-dir .sdddata --out /tmp/ingest.json
sddctx dbq --data-dir .sdddata --kind spec --text "订单 状态 金额 过滤" --out /tmp/dbq.json

# 上下文正确：重置后规格为 v1，不应出现 ORD-004/ORD-005
sddctx context --project demo_project --data-dir .sdddata --task-file samples/task-T001.md --no-state

# 规格更新后重新导入：必须出现 ORD-004/ORD-005
cp -f samples/spec_update/SPEC-order-query.md demo_project/specs/SPEC-order-query.md
sddctx ingest --project demo_project --data-dir .sdddata
sddctx context --project demo_project --data-dir .sdddata --task-file samples/task-T001.md --no-state

# 代码修改有效：修改前必须失败（exit 1），MiniMax 改完必须全过（exit 0）
sddctx verify --project demo_project --label before
MINIMAX_API_KEY=... sddctx patch --project demo_project --data-dir .sdddata --task-file samples/task-T001.md
sddctx verify --project demo_project --label after

# 状态能够复用：save → 重启 Server → 新进程 show
sddctx state save --task-file samples/task-T001.md --phase manual --done "手工验证"
bash scripts/stop_server.sh && bash scripts/start_server.sh
sddctx state show --task-id T-001          # 空状态时 exit 3，有记录时输出 phase/done/todo

# 跑完 run_demo.sh 后一键自检 6 项验收
python3 scripts/check_evidence.py evidence
```

## 7. evidence/ 里有什么

| 文件 | 对应验收项 | 说明 |
|---|---|---|
| `run_transcript.log` | MiniMax 实际参与 / 能够运行 | 12 步全部命令、退出码、测试与模型的原始回显 |
| `step1_state_show_before.json` | 状态能够复用 | 空状态起步（exit 3，PowerContext 无 T-001） |
| `step2_init.json`、`step2_ingest_specv1.json` | 数据库实际参与 | seekdb 库路径、集合、块数 |
| `step3_verify_before.json`、`logs/pytest_before_*.log` | 代码修改有效 | 修改前：目标用例功能性失败，回归全过 |
| `step4_context_specv1.{json,md}` | 上下文正确 | v1 上下文（无 ORD-004/005）+ 检索日志 + 来源核验 |
| `step5_ingest_specv2.json` | 上下文正确 | 规格 v2 增量摄取：`added=2 updated=1` |
| `step6_context_specv2.{json,md}` | 上下文正确 | 同一任务重新检索，出现 ORD-004/ORD-005 |
| `step7_state_planned.json`、`step10_state_verified.json` | 状态能够复用 | 规划/验证两个阶段写入 PowerContext |
| `step8_minimax_run.json` | MiniMax 实际参与 | 送模型的完整上下文（`context_markdown`）、模型原始输出（`raw_model_output`，含推理模型的思考段）、剥离思考后的答案（`model_answer`）、`usage`/`finish_reason`/`elapsed_ms`/`attempts`、diff、备份位置 |
| `step8_code_diff.patch`、`code_before/`、`code_after/` | MiniMax 实际参与 / 代码修改有效 | 与提交代码逐行对应的差异 |
| `step9_verify_after.json`、`logs/pytest_after_*.log`、`step9_code_after.tar.gz` | 代码修改有效 | 修改后目标 + 回归全部通过 |
| `step11_state_show_after.json`、`step11_context_final.{json,md}` | 状态能够复用 | 重启 Server 后新进程回读状态，且状态进入后续上下文 |
| `step12_dbq_*.json` | 数据库实际参与 | 三类资料（spec/code/test）的真实检索结果与查询语句 |
| `step12_seekdb_dir.txt` | 数据库实际参与 | 运行当时的 seekdb 数据目录快照（`du -sh`、文件数、最大的数据文件、manifest 概览）。`.sdddata/` 运行当时 567M（23 个文件）且不入库、`reset.sh` 会清空，这份文本快照保证「库里真有数据」在不重跑时也能核对 |
| （step13 输出在 transcript 末尾） | 全部 6 项 | `check_evidence.py` 的 38 项 PASS/FAIL 结论，逐条对应题面验收条件 |

## 8. 重置

```bash
bash scripts/reset.sh              # 业务工程回到改前基线 + 清空 seekdb；保留 PowerContext 状态（演示复用）
bash scripts/reset.sh --pc-reset   # 连 PowerContext 任务状态一起清空，回到完全空状态
bash scripts/reset.sh --committed  # 反向：把业务工程还原成仓库提交态（MiniMax 改后 v2），不清 seekdb
```

`evidence/` 不会被 `reset.sh` 删除（只有 `run_demo.sh` 的正常全流程会覆盖它），随时可以在两个状态之间来回切换并复核：

```bash
bash scripts/reset.sh && cd demo_project && python -m pytest tests -q -o addopts=   # 改前基线：6 failed / 8 passed
cd .. && bash scripts/reset.sh --committed
cd demo_project && python -m pytest tests -q -o addopts=                            # 提交态：14 passed
cd .. && python3 scripts/check_evidence.py evidence demo_project                    # 38 项仍应全 PASS
```

> `check_evidence.py` 的「改后代码落到工作区/归档」一项在两种工作区状态下都成立：工作区等于 `code_after` 时直接通过；工作区已被 `reset.sh` 恢复成 `code_before` 时，改为核对 `evidence/step9_code_after.tar.gz` 与 `code_after/` 一致。

## 9. 已知限制与常见问题

1. **`pip list` 在个别 venv 里报错**：不影响使用，验证安装可用 `python -c "import importlib.metadata as m;print(m.version('pyseekdb'))"`。
2. **稠密向量是确定性哈希 n-gram（256 维），不是下载的大模型 embedding**。原因：评审要从干净环境复现，向量检索不能依赖网络与模型文件；关键词召回交给 seekdb 全文索引（IK 分词），两者混合（RRF）后效果足以支撑上下文选择。
3. **PowerContext 状态载荷上限 8192 UTF-8 字节**：`taskrecord.py` 超限时按 notes → results 的顺序裁剪，并在记录里保留裁剪标记。
4. **`verify` 依赖 `demo_project/tests` 内的 `conftest.py`** 注入 `src` 路径；不要改 `pytest.ini` 的 `testpaths`。
5. **step1 的 exit 3 与 step3 的 exit 1 是预期结果**，脚本不计入异常步骤；`run_demo.sh` 的总退出码只反映真实异常。
5b. **`run_demo.sh` 的三个门禁按「先只读检查、后破坏性动作」排序**：依赖检查 → 密钥检查 → 才复位 `demo_project/` 并清空证据目录。这样评审在没有 Key、没装依赖、或 MiniMax 服务异常的任一情况下，都不会破坏仓库里已归档的证据与提交态代码（干净环境彩排实测见「技术使用记录」开发记录第 13 条）。
6. **端口 18081 被占用**：`POWERCONTEXT_PORT=18082 bash scripts/start_server.sh`，同时 `export POWERCONTEXT_URL=http://127.0.0.1:18082`。
7. **MiniMax Key 与模型名**：`MINIMAX_API_KEY` 只在运行时从环境变量读取，作品不内置任何密钥、不写入证据文件（`grep -rl sk-api evidence/` 为空）。报 404 `The model ... is no longer available` = 模型名已下线（换 `MiniMax-M3`）；报 402 `insufficient balance (1008)` = 该 Key 是按量付费 Key 且账户无余额，需改用大赛赠送 Token Plan 对应的订阅 Key 或充值，程序会把 MiniMax 返回的状态码与错误体原样打印出来（不含 Key），便于区分这两类问题。
8. **seekdb 本地数据目录较大**：`.sdddata/seekdb.db/`（嵌入式实例的数据目录，本次样例约 200–300MB）与 `.pcserver/home` 都在 `minimax/` 内且已被 `.gitignore` 忽略；`bash scripts/reset.sh` 会清掉它们，重跑自动重建。
9. **推理模型的回答格式**：MiniMax-M3 把思考写在 `message.content` 的 think 标签块里、答案在块之后；`minimax_client._strip_think()` 先剥思考，再按「围栏代码块 / 整段文本 / 括号配对扫描」三级解析约定的 files JSON。解析不出来或 `finish_reason=length` 时自动追加重试（`MINIMAX_ATTEMPTS`），原始输出始终落盘，失败日志也留在 `run_transcript.log`。
10. **模型输出不保证逐字复现**：题面明确「不要求模型重新生成完全相同的补丁」。若某次模型越界（如试图改测试），`patcher.py` 会拒绝并报错，重跑 `sddctx patch` 即可，失败日志同样保留在 `run_transcript.log`。
