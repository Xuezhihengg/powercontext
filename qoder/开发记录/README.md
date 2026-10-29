# Qoder 开发记录

本项目「知栈 StudyStack」全程使用 **Qoder CLI（QoderCN）** 开发：需求拆解、代码生成、
问题修复与界面打磨都在 Qoder 会话中完成，产物直接落在 `qoder/app/`。

## 账号信息

| 项目 | 值 |
| --- | --- |
| 工具 | Qoder CLI CN（`qoderclicn`）v1.1.80 |
| 登录方式 | 浏览器授权登录（`qoder-browser`） |
| 用户名 | `aliyun0432172189` |
| **Qoder 账号 UID** | **`01a18344-30a7-7d75-9bad-c037d0c83971`** |
| 账号类型 | `personal_professional_trial` |

UID 取自 Qoder CLI 登录后调用 `GET https://openapi.qoder.com.cn/api/v2/quota/usage` 的返回，可在
`~/.qoder-cn/logs/runs/*/qodercli.log` 中按 `userId` 检索到同值。

## 会话清单

4 个会话，共约 25 分钟实际编码时间（2026-10-29 00:10 → 00:58），工作目录
`powercontext/qoder`，原始记录见 `原始会话/*.jsonl`。

| # | 会话 ID | 时间 | 目标 | 结果 |
| --- | --- | --- | --- | --- |
| 1 | `67fd1690-f210-45f0-a711-44c947e4ba39` | 00:10:30 – 00:23:10 | 依据《需求规格.md》从零实现整个项目 | 生成 16 个文件：Vite+TS 前端、Express+seekdb 后端、Transformers.js Worker、smoke 脚本，`npm run build` 通过 |
| 2 | `62981e7b-d8df-4eb9-b888-38572b00c1a6` | 00:23:45 – 00:27:11 | 修 smoke 的 localhost/::1、升级 transformers 3.x、WebGPU/WASM 降级、本地模型托管 | 依赖换为 `@huggingface/transformers@3.7.5`，worker 上报后端/精度/体积，smoke 全 PASS |
| 3 | `d789a075-5421-416b-a3f2-bc8320ff961f` | 00:36:54 – 00:40:45 | 修导入按钮 disabled、加「一键导入示例笔记」、薄弱点可直接标记 | 新增 `public/notes/sample.json`（12 篇）与示例导入按钮；薄弱点/全部记录可写回掌握度 |
| 4 | `9f442062-859b-41e5-8177-daf0aa2ff235` | 00:53:24 – 00:58:08 | 界面打磨：按钮宽度、模型徽标、当前课程头、结果卡、再次复习 | 6 项改动完成，`npm run build` 通过 |

## 关键 Prompt（节选）

**会话 1（初始开发）**

> 你是本项目的开发工程师。请阅读附件《需求规格.md》，在 ./app 目录里从零实现「知栈 StudyStack」课程笔记复习助手。
> 要求：1) 先给出需求拆解与文件计划；2) 逐个文件写完整代码（Vite+TypeScript 前端、Express+seekdb 后端、
> Transformers.js Worker、脚本）；3) 运行 npm install 与 npm run build，自己修复所有编译错误；
> 4) 不要修改 app 目录以外的任何文件；5) 最后列出创建/修改的文件清单和遗留问题。
> seekdb 用法：new SeekdbClient({path})，Schema/FulltextIndexConfig('ngram',{ngram_token_size:2})/
> VectorIndexConfig({hnsw:{dimension:512,distance:'cosine'},embeddingFunction:null})，
> 写入用 collection.upsert + collection.refresh_index()，混合检索用
> client.execute('SET @search_parm = ?',[json]) + SELECT DBMS_HYBRID_SEARCH.GET_SQL('<表名>', @search_parm)…

**会话 2（能力修复）**

> 1) smoke.mjs 里 API 用 http://localhost:8787 在本机 Node 会解析到 ::1 导致 fetch failed，改成 127.0.0.1:8787；
> 2) 依赖必须换成 @huggingface/transformers@3.7.5（v2 不支持 WebGPU 与 dtype），worker 需要 navigator.gpu 探测 → device:'webgpu'，
> 失败自动重建 device:'wasm'；dtype 支持 q8(默认) 与 fp16；优先从本地 /models 加载；
> 3) 服务端要静态托管 app/models 到 /models；4) 确保 npm run build 通过，smoke 全部 PASS。

**会话 3（可用性修复）**

> 1) 新建课程成功后「开始导入」按钮仍是 disabled（renderImport 只在初始化时跑过一次），点击无反应；
> 2) 新增「一键导入示例」：把 public/notes/ml 下 12 篇示例笔记做成 public/notes/sample.json，导入页加按钮；
> 3) 薄弱点页每个条目要能直接标记 会/模糊/不会 并写回服务端，标记后立即刷新列表；
> 4) 修完请启动服务自测：新建课程→导入示例→检索→加入复习→标记掌握度，然后 npm run build。

**会话 4（界面打磨）**

> 1) 「检索」按钮现在被拉伸占满，改成 flex:0 固定宽度；
> 2) header 右侧新增常驻徽标（如「WebGPU · q8 · 22.9MB」），后端/精度/体积来自 worker 上报；
> 3) 检索页、导入页顶部显示当前课程名；4) 检索结果显示来源文件、分块号、得分，加入复习后按钮置为「已加入」；
> 5) 薄弱点条目显示掌握度标签、复习次数与「再次复习」；6) 颜色与间距统一，npm run build 必须通过。

## Qoder 的产出

以会话 1 的收尾清单为例，Qoder 自行规划并写出了：

```
package.json / vite.config.ts / tsconfig.json / index.html / .gitignore
server/index.mjs            Express 路由（collections / import / search / review）
server/seekdb.mjs           seekdb 封装：collection schema、upsert、DBMS_HYBRID_SEARCH、review_progress 表
src/embedding.ts + worker.ts Web Worker 内 Transformers.js，WebGPU→WASM 降级，本地模型
src/ui.ts (900+ 行)          4 个 tab 的全部界面渲染逻辑
src/api.ts / state.ts / style.css
scripts/smoke.mjs           15 项断言
```

会话 2~4 由「跑起来之后发现的问题」驱动，Qoder 逐条修改并在会话内自己跑 `npm run build`、启动服务复测。

## 人工复核时发现并修复的问题

Qoder 交付后我做了浏览器端实测，以下 4 个问题在 Qoder 代码基础上直接修正（均已回归验证）：

1. **并发调用 seekdb 会让进程退出**：同时点 3 个「加入复习」时 `node server/index.mjs` 直接退出（exit 0），
   前端表现为接口全部 socket hang up。修复：`server/seekdb.mjs` 增加 Promise 队列，把所有数据库操作串行化，
   并把 `/api/collections` 的统计（含 `count()`）也放进同一把锁。
2. **按钮被 flex 拉伸 / 文字竖排**：`.row > * { flex: 1 }` 命中了按钮。修复：按钮 `flex: 0 0 auto` 且 `white-space: nowrap`。
3. **薄弱点页头部不刷新**：`refreshTabHeaders()` 只刷新 import/search 两个 tab，切课后复习页仍显示「尚未选择课程」。
   修复：把 `review` 加进刷新范围。
4. **课程 ID 校验与存储不一致**：前端允许短横线，seekdb 只接受字母数字下划线。修复：校验改为 `^[a-zA-Z0-9_]+$`。

## 复现这些记录

```bash
# 原始会话（本机）
ls ~/.qoder-cn/projects/-Users-xuezhihengg-Documents-Compete-2026OceanBase-powercontext-qoder/*.jsonl
# 仓库内副本
ls qoder/开发记录/原始会话/
```

每条 `.jsonl` 为 Qoder CLI 的完整会话流（用户消息、助手消息、工具调用与输出），
可用 `jq -r 'select(.message.role=="user") | .message.content'` 之类方式滚动查看。
