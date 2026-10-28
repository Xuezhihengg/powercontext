# 知栈 StudyStack — 本地优先的课程笔记复习助手

用 **Qoder 开发**、以 **OceanBase seekdb 1.4.0 嵌入式模式** 作为唯一存储与检索引擎的课程笔记复习助手。
笔记解析、向量化、检索、掌握度记录全流程都在本机完成，不上传任何云端服务。

- 演示站（Qoder Sites 发布，公开访问）：**https://studystack-ca1ud5cmym8.qoder.zone**
- 展示站源码：`qoder/site/`（构建：`node build.mjs`）
- 代码：`qoder/app/`
- 开发记录（Qoder 会话与账号 UID）：`qoder/开发记录/README.md`
- 界面截图：`qoder/截图/`

## 解决什么问题

学生复习时笔记散落在多个 Markdown/TXT 文件里：想找某个知识点只能全文翻找，也不清楚自己到底哪里薄弱。
StudyStack 把「课程笔记」变成可混合检索的知识库，并把每次检索的命中结果沉淀成可跟踪的掌握度，
下次打开先看薄弱点 Top 5。

## 核心能力

1. **多课程知识库**：每门课一个 seekdb collection，支持新建 / 切换 / 删除，展示文档数、分块数、向量维度。
2. **导入笔记**：支持 `.md` / `.txt` / `.json` 批量导入，按句子边界分块（分块大小、重叠可配置），一键导入内置的 12 篇机器学习示例笔记。
3. **浏览器本地向量化**：Web Worker 内运行 Transformers.js（`Xenova/bge-small-zh-v1.5`，512 维，q8 量化，约 22.9MB），**WebGPU 优先、失败自动降级 WASM**，模型文件由本机 `/models` 静态托管。
4. **库内混合检索**：查询向量同样在浏览器算好后传给服务端，服务端调用 seekdb 的 `DBMS_HYBRID_SEARCH`，**一条 SQL 内**完成全文检索（ngram）+ 向量近邻（HNSW cosine）+ RRF 融合，返回得分与原文。
5. **复习与掌握度**：检索结果可「加入复习」，标记 会 / 模糊 / 不会，写入 seekdb 结构化表 `review_progress`；薄弱点 Top 5 按掌握度升序、复习次数降序排列，可「再次复习」跳回原文。
6. **状态可见**：顶栏常驻模型徽标（后端 · 精度 · 体积），检索区显示「向量化 / seekdb 检索 / 总计」耗时，刷新后当前课程与复习进度保持。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | Vite 6 + TypeScript，原生 DOM（无框架），深色中文界面 |
| 向量化 | `@huggingface/transformers` 3.7.5，Web Worker + WebGPU/WASM |
| 后端 | Node.js + Express 4 |
| 存储 / 检索 | seekdb 1.4.0（`seekdb` npm 包，嵌入式，`SEEKB_PATH=./data/study.db`） |

## 目录结构

```
qoder/
├── app/
│   ├── src/            # 前端：ui.ts 界面 / embedding.ts+worker.ts 向量化 / api.ts 请求 / state.ts 状态
│   ├── server/         # index.mjs 路由；seekdb.mjs 全部数据库操作（含混合检索 SQL）
│   ├── scripts/        # smoke.mjs 冒烟测试
│   ├── public/notes/   # ml/ 12 篇示例笔记、ds/ 6 篇、sample.json
│   ├── models/         # bge-small-zh-v1.5（本地模型，gitignore）
│   ├── data/           # seekdb 数据文件（gitignore）
│   └── dist/           # 构建产物（gitignore）
├── 截图/               # 4 张实测界面截图
├── site/               # Qoder Sites 展示站（静态）
└── 需求规格.md          # 交给 Qoder 的最初需求文档
```

## 环境要求

- Node.js ≥ 20（实测 Node v25.9.0，macOS arm64）
- 无需单独安装 OceanBase / MySQL 服务：seekdb 以嵌入式方式在进程内运行
- 模型约 159MB（含 fp32/fp16/q8 三份 ONNX），只加载 q8 的 22.9MB

## 准备模型

`models/` 已加入 `.gitignore`，克隆后需自行放置模型文件：

```bash
cd qoder/app
# 方式一：HuggingFace CLI（国内可先 export HF_ENDPOINT=https://hf-mirror.com）
huggingface-cli download Xenova/bge-small-zh-v1.5 --local-dir models/Xenova/bge-small-zh-v1.5
```

需要的文件：`config.json`、`tokenizer.json`、`tokenizer_config.json`、`special_tokens_map.json`、`vocab.txt`、
`onnx/model.onnx`、`onnx/model_fp16.onnx`、`onnx/model_quantized.onnx`。
`src/worker.ts` 里 `env.localModelPath = '/models/'`、`env.allowRemoteModels = false`，因此**不会**在运行时访问外网。

## 启动

```bash
cd qoder/app
npm install          # 已带 .npmrc（legacy-peer-deps=true）
npm run dev          # 同时启动 API(8787) 与 Vite(5173)
```

打开 <http://localhost:5173>。首次进入会加载模型，顶栏出现 `WebGPU · q8 · 22.9MB` 后即可使用。

其他脚本：

```bash
npm run build        # 前端构建，产物 dist/
npm run preview      # 预览构建产物
npm run server       # 只启动 API（8787）
npm run smoke        # 冒烟测试（需 API 已启动）
```

## 验证样例（含预期结果）

1. 「课程管理」新建课程 `ml_basics` → 课程列表出现 `ml_basics`，点击「切换」设为当前课程。
2. 「导入笔记」点击「导入示例笔记（机器学习 12 篇）」→ 进度条走满，提示 `成功导入 12 个示例分块`，
   列表显示 12 篇笔记各 1 个分块。
3. 「检索复习」输入 `过拟合太严重应该怎么缓解` → 结果卡片得分约 `0.031x`，耗时行形如
   `向量化: 29ms | seekdb 检索: 10ms | 总计: 39ms`（机器不同会有波动），Top 3 预期命中：
   - `ID: ml-07_0` 来源 `决策树`（预剪枝/后剪枝控制复杂度）
   - `ID: ml-02_0` 来源 `正则化`（L1/L2、Dropout）
   - `ID: ml-03_0` 来源 `偏差方差`（高偏差欠拟合、高方差过拟合）
4. 对上述 3 条依次「加入复习」→ 「薄弱点」页出现这 3 条记录，复习次数为 1。
5. 在薄弱点页把其中两条标为「不会」、一条标为「会」→ 「薄弱知识点 Top 5」里两条「不会」排在前面；
   刷新页面后当前课程与掌握度仍在（状态存 localStorage，掌握度存 seekdb）。

命令行等价验证：

```bash
node scripts/smoke.mjs
# 覆盖：建课 → 导入 → 增量写入 → 混合检索 → 掌握度写入/读取 → 薄弱点排序 → 课程隔离 → 清理
# 预期：All tests PASSED
```

## seekdb 是怎么用的

- 每门课一个 collection，schema：`fulltextIndex = ngram(ngram_token_size=2)`，
  `vectorIndex = HNSW(dimension=512, distance=cosine)`，`embeddingFunction = null`（向量由客户端算好传入）。
- 混合检索（`server/seekdb.mjs`）：

  ```sql
  SET @search_parm = '{"query":{"query_string":{"fields":["document"],"query":"..."}},
                       "knn":{"field":"embedding","k":40,"query_vector":[...]},
                       "rank":{"rrf":{"rank_window_size":64,"rank_constant":60}},"size":10}';
  SELECT DBMS_HYBRID_SEARCH.GET_SQL('c$v2$<collectionId>', @search_parm) AS q FROM dual;
  -- 执行 GET_SQL 生成的 SQL；嵌入式构建下去掉 APPROXIMATE 走精确扫描，RRF 融合仍在库内完成
  ```

  全文、向量、融合三件事都在 seekdb 单条 SQL 里完成，应用层只做参数拼装与结果映射。
- 复习掌握度落在普通 SQL 表 `review_progress`（`id, collection_id, chunk_id, text, file_name, mastery, review_count, last_reviewed`），
  薄弱点与全部记录都用表查询排序，不依赖内存。
- **并发说明**：seekdb 原生绑定不支持并发调用（并发会直接终止进程），
  因此 `server/seekdb.mjs` 用一条 Promise 队列把所有数据库操作串行化，`/api/collections` 的统计也在同一把锁内完成。

## HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| POST | `/api/collections` | 新建课程（`courseId` 仅字母数字下划线） |
| GET | `/api/collections` | 课程列表 + 文档/分块数/维度 |
| DELETE | `/api/collections/:courseId` | 删除课程 |
| POST | `/api/import` | 写入分块（`courseId`, `chunks[{id,text,embedding,fileName,chunkIndex}]`） |
| POST | `/api/search` | 混合检索（`courseId`, `query`, `vector`, `topK`） |
| POST | `/api/review/add` | 加入复习 |
| POST | `/api/review/mastery` | 更新掌握度 |
| GET | `/api/review/weak/:courseId` | 薄弱点 Top 5 |
| GET | `/api/review/all/:courseId` | 全部复习记录 |

## 已知限制

- 嵌入式 seekdb 为单进程使用，服务端未做多实例部署；数据库操作已串行化，但高并发导入仍是单通道。
- 模型首次加载需要几秒（WebGPU 约 2~3s，WASM 更慢）；无 WebGPU 的浏览器会自动降级到 WASM，检索耗时会上升。
- 分块按中英文句子边界切分，未做语义分块；示例笔记每篇正好一个分块，便于对照结果。
