# 鲸落酒馆 · 老账房

> 一个会跨会话记住你每件荒唐事的酒馆 NPC。你在柜台前赊账、撒谎、往汤里加料，
> 账房先生老周都会记进《鲸落账本》；换个新对话再来，他照样能翻出旧账，连本带利地阴阳你。

- 参赛方向：Just for Fun / 互动剧情与角色扮演
- 核心编排：Dify Chatflow（1 个开始节点、4 个代码节点、4 个 HTTP 节点、1 个条件分支、1 个 LLM、2 个回答节点）
- 记忆与上下文：PowerContext Server HTTP API（`/v1/scopes`、`/v1/memory/search`、`/v1/memory/remember`）

## 1. 玩法

1. 打开应用，先填「你的名号」（例如 `阿满`）。名号只在本次对话里固定。
2. 之后每发一句话，就是你在酒馆里干的一件事：
   - `我把盐当成糖，倒进了麦酒桶`
   - `我赊了三杯麦酒，还把账本上的名字改成了隔壁老王`
   - `我今天是来道歉的，上次的麦酒钱我补上`
3. 老周会：先翻账本 → 引用你以前的某件旧事 → 结合本轮动作阴阳怪气 → 再把本轮记上新的一笔。
4. 点「新对话」重新进入，只要还叫 `阿满`，他仍然记得你之前干过什么。
5. 每次回答底部都有一张「账本回执」，直接展示本次检索条数、命中的旧账摘录、写入的 `entry_id` 和好感度，方便核对 PowerContext 真的读写了。

好玩点在于「你越赖账，他越有据可查」：玩家会主动尝试更离谱的恶作剧，看 NPC 怎么把旧账和新账串起来算利息。

## 2. Dify 与 PowerContext 的分工

| 组成 | 在本作品中的作用 |
| --- | --- |
| Dify Chatflow | 收集名号、清洗输入、编排四次 PowerContext 调用、条件降级、组装提示词、调用模型、拼接最终回答 |
| PowerContext `POST /v1/scopes` | 用 `idempotency_key = tavern-ledger-v1:<名号>` 创建/复用玩家账本 scope，实现跨会话身份绑定 |
| PowerContext `POST /v1/memory/search` | 两路检索：① 用本轮动作聚焦查询“相关旧账”；② 用名号查询“整本账”，保证久远旧事也能被翻出 |
| PowerContext `POST /v1/memory/remember` | 每轮把 `玩家<名号>：<动作>` 以 `kind=tavern-deed` 写入账本；重复动作由服务端自动合并 |
| LLM | 只负责“按账本演戏”，不负责记事实；记忆的唯一事实来源是 PowerContext |

## 3. 目录与交付物

```
dify/
├── tavern-ledger.chatflow.yml   # Dify DSL（Chatflow，DSL 版本 0.3.0），导入这个文件
├── README.md                    # 本运行说明
├── code/                        # DSL 中 4 个代码节点的可读源码（由 build_dsl.py 内联进 DSL）
│   ├── prep_inputs.py
│   ├── parse_scope.py
│   ├── summarize_memory.py
│   └── build_footer.py
├── scripts/
│   ├── build_dsl.py             # 由 code/ 重新生成 DSL
│   ├── check_dsl.py             # 导入前静态检查（节点、边、变量引用、代码签名）
│   ├── seed_tavern.py           # 初始化 scope 与预置旧账
│   └── verify_flow.py           # 读取 DSL 离线回放，真实调用 PowerContext 验证跨会话记忆
└── samples/
    └── walkthrough.md           # 验证样例：初始状态、输入、预期、实际输出、恢复方式
```

`code/` 与 DSL 内的代码保持一致；修改代码后执行 `python scripts/build_dsl.py` 重新生成 DSL。

## 4. 版本与依赖

| 项目 | 版本 / 说明 |
| --- | --- |
| Dify | DSL 版本 `0.3.0`，开发基准 Dify `1.3.x`；1.x 后续版本可按“旧版本 DSL”导入并接受版本提示，不建议 Dify 2.x |
| PowerContext | `oceanbase/powercontext` 的 `master`（HTTP API v1）；本题生态分支只承载 `dify/` 等作品资产，不含服务端源码 |
| 模型 | DSL 默认绑定 `langgenius/openai/openai` 的 `gpt-4o-mini`，任意可用 Chat 模型均可替换 |
| 插件 | 不需要自定义插件；只需模型供应商插件（OpenAI 或你替换后的供应商） |
| Python（仅脚本） | 3.11+；`verify_flow.py` 额外需要 `pyyaml`、`httpx` |
| 数据库 | PowerContext 默认 SQLite 即可；本作品未使用 seekdb |

## 5. 快速开始

### 5.1 启动 PowerContext

方式 A（推荐，从官方主分支安装）：

```bash
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
powercontext server run
curl --fail http://127.0.0.1:8000/health/live
```

方式 B（已有 PowerContext 源码时）：

```bash
cd powercontext
uv venv && source .venv/bin/activate
uv pip install -e ".[cli,server]"
powercontext server run
```

> 选题要求提交的 `2026-competition-ecosystem` 分支只包含各赛道作品目录（`dify/`、`gaode/` 等），不包含 PowerContext 服务端源码；服务端请按上面命令从主分支安装。

如果 Dify 跑在 Docker 里，需要让 PowerContext 监听宿主机网卡：

```bash
POWERCONTEXT_SERVER_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true powercontext server run --host 0.0.0.0
```

> 只在可信的本机/内网演示环境这样放开；对外暴露时请按 PowerContext 文档启用 Bearer 认证，并在 4 个 HTTP 节点里补 `Authorization:Bearer <token>` 请求头。

### 5.2 导入 Dify 应用

1. 准备 Dify `1.3.0+`（Docker Compose 自部署或云端工作区均可）。
2. 在「工作室 → 导入 DSL」选择 `dify/tavern-ledger.chatflow.yml`。
3. 打开应用 → 工作流画布 → 右上角「环境变量」，确认 `POWERCONTEXT_BASE_URL`：
   - Dify 与 PowerContext 同机直连：`http://127.0.0.1:8000`
   - Dify 在 Docker Desktop、PowerContext 在宿主机：`http://host.docker.internal:8000`
   - Linux Docker：给 api 容器加 `extra_hosts: ["host.docker.internal:host-gateway"]`，或填宿主机局域网 IP
   - Dify 云端：填 PowerContext 的公网 HTTPS 地址（云端无法访问你的 localhost）
4. 打开「老周开口」LLM 节点，重新选择你有凭据的模型（默认 `gpt-4o-mini`）。
5. 发布应用，进入「运行」/「预览」。

> 若 HTTP 节点报代理或 403：Dify 的 HTTP Request 节点会经过 SSRF 代理，部分版本默认拦截私网地址。可把 PowerContext 放到公网 HTTPS 域名，或按 Dify 文档调整 `SSRF_PROXY_*` / 代理白名单后重试。

### 5.3 初始化旧账（可选）

不初始化也能玩：第一名玩家会从空账本开始。想让演示立刻有“旧账”，可预置：

```bash
python dify/scripts/seed_tavern.py \
  --base-url http://127.0.0.1:8000 \
  --player 阿满 \
  --verify
```

脚本会自动创建/复用 scope，并写入 3 条示例旧账（盐、赊酒改名、骗烤鸡）。也可用 `--deed "..."` 自定义，`--no-seed` 只建账本。

### 5.4 名号、会话与 scope 的对应关系

- Dify 开始变量 `player_name` = 玩家名号，只在一次对话内固定。
- 代码节点把名号清洗后拼成 `idempotency_key = tavern-ledger-v1:<名号>`。
- PowerContext 对同一 `idempotency_key` 幂等返回同一个 `scope_id`，所以“新对话 + 同名号”仍然命中同一本账。
- 不同名号得到不同 scope，互不可见；改名即换一本新账。
- 写入条目统一 `kind=tavern-deed`，正文格式 `玩家<名号>：<动作>`（≤600 字）。

## 6. 验证样例

完整步骤、预期与实际输出见 [`samples/walkthrough.md`](samples/walkthrough.md)。核心是三次“新会话”：

| 轮次 | 输入（名号均为阿满） | 预期 |
| --- | --- | --- |
| A（新会话） | `我把盐当成糖，倒进了麦酒桶` | 账本 0 条旧账，老周初次见面口气；回执显示新 `entry_id` |
| B（新会话） | `我赊了三杯麦酒，还把账本上的名字改成了隔壁老王` | 检索到 A 的旧账并具体引用，好感度下降 |
| C（新会话） | `我今天什么都没干，就是来道歉的` | 仍能翻出 A、B 两笔旧账；道歉使好感度回升 |

不需要打开 Dify 也能先行验证 DSL 逻辑与 PowerContext 读写：

```bash
# 1) 起一个干净的 PowerContext（另开终端）
powercontext server run

# 2) 静态检查 DSL
python dify/scripts/check_dsl.py

# 3) 回放 DSL：跑 3 个新会话 + 1 个隔离检查
python dify/scripts/verify_flow.py --base-url http://127.0.0.1:8000
```

成功时最后一行是：

```
OK: 3 sessions shared one scope; reads, writes and player isolation verified.
```

说明：回放器会执行 DSL 里的同一批代码节点、HTTP 节点和条件分支，只把 LLM 换成确定性桩（无模型凭据）。真实台词需在 Dify 中绑定模型体验。

## 7. PowerContext 在本作品中的实际作用（可核对点）

- **读**：`1006 翻旧账` 调 `/v1/memory/search`（本轮动作聚焦查询，`limit=4`）；`1013 取整本账` 再按名号查一次（`limit=20`），两路结果由代码节点合并、去重、取前 8 条注入提示词。
- **写**：`1009 记你一笔` 调 `/v1/memory/remember`，每轮写入 `kind=tavern-deed` 的新条目。
- **身份**：`1003 开账本 / 取账本` 调 `/v1/scopes`，用名号做幂等键，跨会话复用 scope。
- **可视证据**：每条回答末尾的「账本回执」包含 `scope_id`、本轮命中条数、旧账摘录、`mem_ent_...` 条目 ID、好感度。
- **失败降级**：scope 节点配置了 `default-value` 错误策略；服务不可用或响应异常时，条件分支走「账本坏了」回答，而不是整条流程报错。

## 8. 已知限制

- 未配置 Embedding 时，PowerContext 使用 FTS（关键词）检索。因此流程做了两路检索：动作聚焦查询负责“相关”，名号查询负责“翻出整本账”；即使本轮动作和旧账没有共同关键词，NPC 仍能看到旧账。
- 好感度是确定性的规则分（命中旧账越多越低，出现“道歉/赔/请客”等词回升），不是模型自由发挥，便于复现。
- 同一句话重复写入会被 PowerContext 合并，回执显示“重复旧账，已合并（未新增）”。
- DSL 默认模型为 OpenAI `gpt-4o-mini`；没有该模型时需在 LLM 节点改绑。
- HTTP 节点未内置认证头；对外部署请自行加 Bearer Token，避免把账本暴露给任意调用方。
- 回放脚本的 LLM 是桩输出，仅用于验证流程与读写；台词质量以 Dify 实际运行为准。

## 9. 复用与来源

- DSL 的节点字段结构参考 Dify 公开导出的 Chatflow（`version 0.3.0`）写法，节点内容、提示词、代码均为本作品新写。
- PowerContext 接口用法参考仓库内 `docs/zh/docs/develop/api-quickstart.md` 与 `openapi/powercontext.yaml`。
- 未复用需要额外授权的第三方工作流或数据。
