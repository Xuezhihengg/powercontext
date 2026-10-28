# seekdb 端侧迷你知识库

在浏览器本地完成文本向量化，把向量、原文和元数据写入 seekdb，并由 seekdb 在库内完成
「稠密向量 + 全文」混合检索的迷你知识库。推理全程在用户设备上执行，不调用任何云端推理 API。

- 前端：Vite + TypeScript，Transformers.js（ONNX Runtime Web），WebGPU 优先、WASM 自动降级
- 推荐组合：**WebGPU + FP16**（吞吐最高）、**WASM + INT8**（体积最小、质量与 fp32 一致）
- 数据层：seekdb-js 1.4.0（默认嵌入式文件模式，也支持本地 server）
- 混合检索：`collection.hybridSearch()`，库内 `DBMS_HYBRID_SEARCH` + RRF 融合

## 快速开始

环境要求：Node.js ≥ 20、Chrome / Edge 113+（WebGPU 需要 121+）。

```bash
cd stepfun
npm install                      # .npmrc 已设置 legacy-peer-deps
node scripts/fetch-models.mjs    # 预取 3 档 ONNX 权重到 ./models（约 160 MB，可跳过）
# 国内建议：MODEL_HOST=https://modelscope.cn/models MODEL_REVISION=master node scripts/fetch-models.mjs

npm run dev                      # 同时启动 seekdb API (8787) 与 Vite (5173)
# 打开 http://127.0.0.1:5173
```

`models/` 不随仓库提交。存在本地权重时服务端会以 `/models` 提供并关闭远程下载；
没有本地权重时，浏览器按 `MODEL_HOST`（默认 huggingface.co）在线拉取。

首次使用会在浏览器里下载 ONNX 权重（fp32 / fp16 / INT8 三档按需选择），随后命中
浏览器 Cache Storage。seekdb 嵌入式模式首次运行会下载原生绑定到 `~/.seekdb/bindings`。

生产模式：

```bash
npm run build && npm start   # 打开 http://127.0.0.1:8787
```

### 换成 seekdb server 模式

```bash
# 1. 启动 seekdb server（Docker）
docker run -d --name seekdb -p 2881:2881 -e MODE=slim oceanbase/seekdb:latest
# 2. 用 server 模式启动应用（不设置 SEEKB_PATH 即走 server）
unset SEEKB_PATH
SEEKB_HOST=127.0.0.1 SEEKB_PORT=2881 SEEKB_USER=root SEEKB_DATABASE=test npm run dev
```

## 使用流程

1. 在「模型与推理后端」里选模型（默认 `Xenova/bge-small-zh-v1.5`）与精度，点击「加载模型」。
   界面顶部会显示实际使用的后端（WebGPU / WASM）和模型体积、加载耗时。
2. 在「知识库集合」新建或选择集合（向量维度由当前模型决定，集合与维度绑定）。
3. 导入 `.txt / .md / .json / .csv` 文件，或点击「导入 30 篇示例」。
   导入过程展示分块、向量化进度，以及写入 seekdb、刷新索引的耗时。
4. 输入查询，选择「混合检索（向量+全文）」，查看排序结果、得分与原文。
5. 「基准测试」页可一键跑固定语料与查询集，得到分阶段耗时、Recall@5 / nDCG@5，
   并导出 JSON。

## 目录结构

```
stepfun/
├── server/
│   ├── index.mjs         # REST API（Express）
│   └── kb.mjs            # seekdb 客户端、集合/索引、混合检索
├── src/
│   ├── main.ts           # 界面与业务流程
│   ├── embedder.ts       # Worker 客户端封装
│   ├── embedder.worker.ts# Transformers.js 推理（WebGPU/WASM、dtype、进度）
│   ├── chunker.ts        # 句子边界分块
│   ├── bench.ts          # 基准测试与 Recall@K / nDCG@K
│   └── api.ts            # 前端 API 客户端
├── public/corpus/corpus.json   # 30 篇中文示例语料
├── public/bench/queries.json   # 12 条查询与相关文档标注
├── bench/run-bench.mjs         # 用本机 Chrome 自动跑基准
└── 技术说明.md / 测试报告.md
```

## seekdb 数据结构

每个知识库对应一个 collection（默认 `kb_main`），schema：

```ts
new Schema({
  fulltextIndex: new FulltextIndexConfig('ngram', { ngram_token_size: 2 }), // 中文二元组
  vectorIndex: new VectorIndexConfig({
    hnsw: { dimension: 512, distance: 'cosine' },
    embeddingFunction: null,   // 向量由浏览器算好后传入，服务端不做推理
  }),
})
```

- 主键：`<docId>-<chunkIndex>`
- `document`：分块原文（同时建立 ngram 全文索引）
- `embedding`：浏览器产出的归一化向量（HNSW / cosine）
- `metadata`：`docId / title / source / chunk / createdAt`

写入使用 `collection.upsert()`，随后调用 `collection.refresh_index()` 让新数据立即可检索；
导入接口返回 `writeMs` 与 `refreshMs` 以便观测索引刷新成本。

混合检索在 seekdb 内完成：

```ts
await collection.hybridSearch({
  query: { whereDocument: { $contains: sanitizedQuery } },
  knn: { queryEmbeddings: [queryVector] },
  rank: { rrf: { rankWindowSize: 64, rankConstant: 60 } },
  nResults: 8,
});
```

前端只提交「查询文本 + 查询向量」，两路召回与 RRF 融合由数据库执行，没有客户端拼接。

> 嵌入式构建（seekdb-js 1.4.0 macOS/Linux 原生绑定）里 HNSW 近似索引暂不可查询，
> 因此默认会在 `DBMS_HYBRID_SEARCH` 生成的 SQL 中去掉 `APPROXIMATE`，改由 seekdb 在同一条语句内做
> 精确向量扫描 + 全文 RRF 融合；融合位置不变。连接 seekdb server 时设置 `SEEKB_APPROXIMATE=1`
> 即走原生 HNSW 近似检索。

## 基准测试

```bash
npm run dev                       # 终端 1
npm run bench -- q8 auto          # 终端 2：q8 + 自动后端
npm run bench -- fp16 webgpu fp32 wasm
```

脚本用本机 Chrome（可用 `CHROME_PATH` 覆盖）驱动页面里的 `window.__KB__.bench()`，
结果写入 `bench/results/*.json`。评测集为 30 篇语料 / 12 条查询，指标按文档级去重计算
Recall@5、nDCG@5、MRR@10。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SEEKB_PATH` | `./data/kb.db` | seekdb 嵌入式数据库文件；置空字符串则走 server 模式 |
| `SEEKB_HOST` / `SEEKB_PORT` | `127.0.0.1` / `2881` | server 模式连接参数 |
| `SEEKB_USER` / `SEEKB_PASSWORD` / `SEEKB_DATABASE` | `root` / 空 / `test` | server 模式凭据 |
| `MODEL_HOST` | 空（huggingface.co） | 模型下载站点，国内可设 `https://hf-mirror.com` |
| `PORT` | `8787` | API / 生产静态站点端口 |
| `SEEKB_BINDINGS_BASE_URL` | 官方 S3 | 原生绑定下载地址（离线部署时指到内网镜像） |
| `SEEKB_APPROXIMATE` | `1`（精确扫描） | 置 `1` 使用 HNSW 近似检索（server 模式推荐） |
| `MODEL_ID` / `MODEL_REVISION` | `Xenova/bge-small-zh-v1.5` / `main` | `fetch-models` 使用的模型与分支 |

## 常见问题

- **WebGPU 不可用**：页面顶部会显示 `推理后端 WASM`，核心流程不受影响；也可在「推理后端」下拉框强制指定。
- **首次加载慢**：模型权重 + ONNX Runtime wasm 体积较大，第二次起走浏览器缓存；可在模型面板看到下载进度。
- **维度不一致**：不同模型维度不同（bge-small-zh 512，MiniLM 384），切换模型后请新建集合。
- **找不到原生绑定**：若无法访问默认下载源，设置 `SEEKB_BINDINGS_BASE_URL` 指向可访问的镜像目录，
  或改用 seekdb server 模式。
