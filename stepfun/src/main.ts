import './style.css';
import { api, type CollectionInfo, type SearchResponse } from './api';
import { Embedder, detectWebGPU, type Backend, type Dtype, type InitResult } from './embedder';
import { chunkText } from './chunker';
import { runBench, type BenchReport } from './bench';

const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector(selector) as T;

type DeviceChoice = Backend | 'auto';

const state = {
  embedder: new Embedder(),
  init: null as InitResult | null,
  dim: 0,
  collections: [] as CollectionInfo[],
  current: null as string | null,
  busy: false,
  reports: [] as BenchReport[],
};

const config = { modelHost: '', defaultModel: 'Xenova/bge-small-zh-v1.5', mode: '', localModels: false, localPath: '/models/' };

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch] as string));
}

function toast(message: string, kind: 'info' | 'err' = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${kind === 'err' ? 'err' : ''}`;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), kind === 'err' ? 6000 : 3200);
}

function render() {
  const init = state.init;
  $('#badge-backend').textContent = init ? `推理后端 ${init.backend.toUpperCase()}` : '推理后端 未加载';
  $('#badge-backend').className = `badge ${init ? (init.backend === 'webgpu' ? 'on' : 'warn') : ''}`;
  $('#badge-dtype').textContent = init ? `精度 ${init.dtype}` : '精度 -';
  $('#badge-dtype').className = 'badge';
  $('#badge-seekdb').textContent = `seekdb ${config.mode || '…'}`;
  $('#badge-seekdb').className = 'badge on';
  $('#badge-dim').textContent = init ? `维度 ${init.dim}` : '维度 -';

  const list = $('#kb-list');
  if (!state.collections.length) {
    list.innerHTML = '<div class="empty" style="padding:14px">还没有知识库，先新建一个</div>';
  } else {
    list.innerHTML = state.collections
      .map((c) => `
        <div class="kb-item ${state.current === c.name ? 'active' : ''}" data-kb="${escapeHtml(c.name)}">
          <div>
            <div class="name">${escapeHtml(c.name)}</div>
            <div class="sub">${c.chunks} 块 · ${c.docs ?? '-'} 文档 · ${c.dimension} 维</div>
          </div>
          <button class="danger" data-drop="${escapeHtml(c.name)}">删除</button>
        </div>`)
      .join('');
    list.querySelectorAll<HTMLElement>('[data-kb]').forEach((el) =>
      el.addEventListener('click', (ev) => {
        if ((ev.target as HTMLElement).dataset.drop) return;
        state.current = el.dataset.kb!;
        localStorage.setItem('kb.current', state.current);
        render();
        void loadDocsPreview();
      }),
    );
    list.querySelectorAll<HTMLElement>('[data-drop]').forEach((el) =>
      el.addEventListener('click', async () => {
        const name = el.dataset.drop!;
        if (!confirm(`删除集合 ${name} 及其全部数据？`)) return;
        await api.drop(name);
        if (state.current === name) state.current = null;
        await refreshCollections();
        toast(`已删除 ${name}`);
      }),
    );
  }

  const current = state.collections.find((c) => c.name === state.current);
  $('#current-kb').textContent = current ? `${current.name} · ${current.chunks} 块` : '未选择';
  $('#docs-preview').innerHTML = current
    ? `<div class="meta">维度 ${current.dimension} · 模型 ${escapeHtml(current.model || '-')} · 创建于 ${current.createdAt ? new Date(current.createdAt).toLocaleString() : '-'}</div>`
    : '';
}

async function refreshCollections() {
  const res = await api.list();
  state.collections = res.collections;
  if (!state.current || !state.collections.some((c) => c.name === state.current)) {
    state.current = state.collections[0]?.name ?? null;
    if (state.current) localStorage.setItem('kb.current', state.current);
  }
  render();
}

function setProgress(el: string, percent: number) {
  $(el).style.width = `${Math.max(0, Math.min(100, percent))}%`;
}

async function loadModel(cfg: { dtype: Dtype; device: DeviceChoice; quiet?: boolean }): Promise<{ init: InitResult; embedder: Embedder }> {
  const modelId = ($('#model') as HTMLSelectElement).value || config.defaultModel;
  const requested: Backend = cfg.device === 'auto' ? ((await detectWebGPU()) ? 'webgpu' : 'wasm') : cfg.device;

  if (state.init && state.init.dtype === cfg.dtype && state.init.backend === requested && state.init.modelId === modelId) {
    return { init: state.init, embedder: state.embedder };
  }

  if (state.init) {
    await state.embedder.dispose();
    state.embedder.terminate();
    state.embedder = new Embedder();
    state.init = null;
  }

  const meta = $('#model-meta');
  if (!cfg.quiet) meta.textContent = '正在下载模型…';
  const init = await state.embedder.init(
    { modelId, dtype: cfg.dtype, device: requested, modelHost: config.modelHost || undefined, localModels: config.localModels, localPath: config.localPath },
    (p) => {
      if (p.stage === 'download' && p.total) {
        const pct = (p.loaded / p.total) * 100;
        setProgress('#model-progress', pct);
        if (!cfg.quiet) meta.textContent = `下载 ${p.file} ${(p.loaded / 1048576).toFixed(1)} / ${(p.total / 1048576).toFixed(1)} MB`;
      }
    },
  );
  state.init = init;
  state.dim = init.dim;
  setProgress('#model-progress', 100);
  meta.textContent =
    `模型 ${init.modelId}\n精度 ${init.dtype} · 后端 ${init.backend}${init.fallbackReason ? '（WebGPU 失败已降级）' : ''}\n` +
    `模型体积 ${(init.modelBytes / 1048576).toFixed(1)} MB · 维度 ${init.dim}\n` +
    `加载 ${init.loadMs.toFixed(0)} ms · 预热 ${init.warmMs.toFixed(0)} ms`;
  render();
  if (!cfg.quiet) toast(`模型就绪：${init.backend.toUpperCase()} / ${init.dtype}`);
  return { init, embedder: state.embedder };
}

function currentCollection(): string {
  if (!state.current) throw new Error('请先选择或新建知识库');
  return state.current;
}

async function ensureCollection(dim: number) {
  if (state.current) return state.current;
  const name = 'kb_main';
  await api.create(name, dim, '默认知识库', state.init?.modelId || '');
  state.current = name;
  await refreshCollections();
  return name;
}

interface TextDoc {
  id: string;
  title: string;
  text: string;
}

function hash(input: string): string {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(36);
}

async function fileToDocs(file: File): Promise<TextDoc[]> {
  const text = await file.text();
  if (file.name.endsWith('.json')) {
    try {
      const parsed = JSON.parse(text);
      const arr = Array.isArray(parsed) ? parsed : parsed.docs || parsed.corpus || [];
      return arr
        .map((item: any, index: number) => ({
          id: String(item.id || `${file.name}-${index}`),
          title: String(item.title || item.id || file.name),
          text: String(item.text || item.content || ''),
        }))
        .filter((d: { text: string }) => d.text.trim().length > 0);
    } catch {
      // fall through: treat as plain text
    }
  }
  return [{ id: `${file.name.replace(/\.[^.]+$/, '')}-${hash(text).slice(0, 6)}`, title: file.name, text }];
}

async function ingestDocs(docs: TextDoc[], source: string, dim: number, onProgress?: (msg: string, pct: number) => void) {
  const chunkSize = Number(($('#chunk-size') as HTMLInputElement).value || 400);
  const overlap = Number(($('#chunk-overlap') as HTMLInputElement).value || 60);
  const batchSize = Number(($('#batch-size') as HTMLInputElement).value || 16);
  const target = await ensureCollection(dim);

  const chunks: { id: string; docId: string; title: string; text: string; chunk: number }[] = [];
  for (const doc of docs) {
    chunkText(doc.text, { maxChars: chunkSize, overlap }).forEach((part) => {
      chunks.push({ id: `${doc.id}-${part.index}`, docId: doc.id, title: doc.title, text: part.text, chunk: part.index });
    });
  }
  if (!chunks.length) throw new Error('没有可导入的文本');

  const t0 = performance.now();
  const result = await state.embedder.embed(chunks.map((c) => c.text), batchSize, (msg) => {
    if (msg.stage === 'embed') onProgress?.(`向量化 ${msg.done}/${msg.total}`, (msg.done / msg.total) * 70);
  });
  const embedMs = performance.now() - t0;
  const dims = result.dim;

  onProgress?.('写入 seekdb', 75);
  let writeMs = 0;
  let refreshMs = 0;
  const items = chunks.map((chunk, i) => ({
    id: chunk.id,
    text: chunk.text,
    vector: Array.from(result.vectors.subarray(i * dims, (i + 1) * dims)),
    metadata: {
      docId: chunk.docId,
      title: chunk.title,
      source,
      chunk: chunk.chunk,
      createdAt: Date.now(),
    },
  }));
  for (let i = 0; i < items.length; i += 400) {
    const slice = items.slice(i, i + 400);
    const res = await api.addDocs(target, { items: slice, dimension: dims, model: state.init?.modelId || '' });
    writeMs += res.writeMs;
    refreshMs += res.refreshMs;
  }
  const totalMs = performance.now() - t0;
  onProgress?.('完成', 100);
  await refreshCollections();

  const stats = { docs: docs.length, chunks: chunks.length, embedMs, writeMs, refreshMs, totalMs, dim: dims };
  $('#import-meta').textContent =
    `文档 ${stats.docs} · 分块 ${stats.chunks} · 维度 ${stats.dim}\n` +
    `向量化 ${stats.embedMs.toFixed(0)} ms · 写入 ${stats.writeMs.toFixed(0)} ms · 刷新 ${stats.refreshMs.toFixed(0)} ms · 合计 ${stats.totalMs.toFixed(0)} ms`;
  return stats;
}

async function handleFiles(files: FileList | File[]) {
  if (!state.init) throw new Error('请先加载模型');
  state.busy = true;
  try {
    const docs: TextDoc[] = [];
    for (const file of Array.from(files)) {
      if (file.name.endsWith('.json')) docs.push(...(await fileToDocs(file)));
      else if (/\.(txt|md|markdown|log|csv)$/i.test(file.name)) docs.push(...(await fileToDocs(file)));
      else toast(`跳过不支持的文件 ${file.name}`, 'err');
    }
    await ingestDocs(docs, 'file', state.dim, (msg, pct) => {
      $('#import-status').textContent = msg;
      setProgress('#import-progress', pct);
    });
    toast(`已导入 ${docs.length} 篇文档`);
  } finally {
    state.busy = false;
    $('#import-status').textContent = '';
  }
}

async function ingestSample() {
  if (!state.init) throw new Error('请先加载模型');
  const corpus = await fetch('/corpus/corpus.json').then((r) => r.json());
  const docs: TextDoc[] = corpus.map((d: any) => ({ id: d.id, title: d.title, text: d.text }));
  const stats = await ingestDocs(docs, 'sample', state.dim, (msg, pct) => {
    $('#import-status').textContent = msg;
    setProgress('#import-progress', pct);
  });
  toast(`示例语料导入完成：${stats.chunks} 块`);
}

function highlight(text: string, query: string): string {
  const terms = query.split(/\s+/).map((t) => t.trim()).filter((t) => t.length >= 2).slice(0, 8);
  let html = escapeHtml(text);
  for (const term of terms) {
    const safe = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    html = html.replace(new RegExp(safe, 'gi'), (m) => `<mark>${m}</mark>`);
  }
  return html;
}

async function doSearch(): Promise<SearchResponse | null> {
  const query = ($('#query') as HTMLInputElement).value.trim();
  const mode = ($('#mode') as HTMLSelectElement).value;
  const k = Number(($('#topk') as HTMLInputElement).value || 8);
  if (!query) {
    toast('请输入查询内容', 'err');
    return null;
  }
  if (!state.init) {
    toast('请先加载模型', 'err');
    return null;
  }
  const name = currentCollection();
  const t0 = performance.now();
  let vector: number[] | undefined;
  let queryEmbedMs = 0;
  if (mode !== 'fulltext') {
    const r = await state.embedder.embed([query], 1);
    queryEmbedMs = r.ms;
    vector = Array.from(r.vectors.subarray(0, r.dim));
  }
  const res = await api.search(name, { query, vector, k, mode });
  const e2e = performance.now() - t0;

  $('#search-timings').innerHTML = `
    <span class="chip">查询向量化 <b>${queryEmbedMs.toFixed(1)} ms</b></span>
    <span class="chip">seekdb 检索 <b>${res.tookMs.toFixed(1)} ms</b></span>
    <span class="chip">端到端 <b>${e2e.toFixed(1)} ms</b></span>
    <span class="chip">引擎 <b>${escapeHtml(res.engine)}</b></span>
    ${res.fulltextSkipped ? '<span class="chip">全文查询为空，仅走向量</span>' : ''}`;

  const box = $('#results');
  if (!res.hits.length) {
    box.innerHTML = '<div class="empty">没有命中的文档。确认索引已刷新，或换一个查询词。</div>';
    return res;
  }
  box.innerHTML = res.hits
    .map(
      (hit, i) => `
      <article class="hit">
        <div class="head">
          <span class="rank">#${i + 1}</span>
          <span class="title">${escapeHtml(hit.title || hit.docId || '未命名')}</span>
          <span class="score">score ${hit.score == null ? '-' : hit.score.toFixed(4)}</span>
        </div>
        <div class="text">${highlight(hit.text, query)}</div>
        <div class="path">doc=${escapeHtml(String(hit.docId || ''))} · chunk=${hit.chunk} · source=${escapeHtml(hit.source || '')} · id=${escapeHtml(hit.id)}</div>
      </article>`,
    )
    .join('');
  return res;
}

async function loadDocsPreview() {
  if (!state.current) return;
  try {
    const res = await api.docs(state.current, 5);
    if (!res.docs.length) {
      $('#docs-preview').innerHTML += '<div class="meta">集合为空</div>';
      return;
    }
    $('#docs-preview').innerHTML += res.docs
      .map((d) => `<div class="meta">• ${escapeHtml(d.metadata?.title || d.id)} — ${escapeHtml(d.text.slice(0, 60))}…</div>`)
      .join('');
  } catch (err) {
    console.warn(err);
  }
}

function renderBench() {
  const box = $('#bench-report');
  if (!state.reports.length) {
    box.innerHTML = '<div class="empty">还没有运行基准测试</div>';
    return;
  }
  const rows = state.reports
    .map(
      (r) => `<tr>
        <td>${r.model.split('/').pop()}</td>
        <td>${r.dtype}</td>
        <td>${r.backend}</td>
        <td class="num">${(r.modelBytes / 1048576).toFixed(1)} MB</td>
        <td class="num">${Math.round(r.docThroughputCharsPerSec)} 字/秒</td>
        <td class="num">${r.timings.writeMs.toFixed(0)}+${r.timings.refreshMs.toFixed(0)} ms</td>
        <td class="num">${r.timings.queryEmbedMedianMs.toFixed(1)} ms</td>
        <td class="num">${r.timings.searchMedianMs.toFixed(1)} ms</td>
        <td class="num">${r.timings.e2eMedianMs.toFixed(1)} ms</td>
        <td class="num">${r.quality.recallAt5.toFixed(3)}</td>
        <td class="num">${r.quality.ndcgAt5.toFixed(3)}</td>
      </tr>`,
    )
    .join('');
  const baseline = state.reports.find((r) => r.dtype === 'fp32');
  const compression = baseline
    ? state.reports
        .filter((r) => r.dtype !== 'fp32')
        .map((r) => `${r.dtype}: ${(baseline.modelBytes / r.modelBytes).toFixed(2)}×`)
        .join(' · ')
    : '-';
  box.innerHTML = `
    <table>
      <thead><tr><th>模型</th><th>精度</th><th>后端</th><th>体积</th><th>向量化吞吐</th><th>写入+刷新</th><th>查询向量化</th><th>seekdb 检索</th><th>端到端</th><th>Recall@5</th><th>nDCG@5</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="meta">压缩比（相对 fp32）：${compression}</div>`;
}

async function runBenchUI(dtypeArg?: Dtype, deviceArg?: DeviceChoice) {
  const dtype = (dtypeArg || ($('#bench-dtype') as HTMLSelectElement).value) as Dtype;
  const device = (deviceArg || ($('#bench-device') as HTMLSelectElement).value) as DeviceChoice;
  const corpus = await fetch('/corpus/corpus.json').then((r) => r.json());
  const queries = await fetch('/bench/queries.json').then((r) => r.json());

  const log = $('#bench-log');
  log.textContent = '';
  const onProgress = (msg: string, pct = 0) => {
    log.textContent += `${new Date().toLocaleTimeString()} ${msg}\n`;
    log.scrollTop = log.scrollHeight;
    setProgress('#bench-progress', pct);
  };

  $('#run-bench').setAttribute('disabled', 'true');
  try {
    const report = await runBench({ dtype, device, api, corpus, queries, loadModel, onProgress });
    state.reports.push(report);
    renderBench();
    $('#bench-meta').textContent =
      `${report.backend} / ${report.dtype} · 分块 ${report.chunks} · 语料 ${report.corpusChars} 字\n` +
      `加载 ${report.timings.modelLoadMs.toFixed(0)} ms · 文档向量化 ${report.timings.docEmbedMs.toFixed(0)} ms · 检索中位数 ${report.timings.searchMedianMs.toFixed(1)} ms`;
    localStorage.setItem('kb.reports', JSON.stringify(state.reports));
    toast('基准测试完成');
    return report;
  } catch (err) {
    onProgress(`失败：${(err as Error).message}`);
    toast((err as Error).message, 'err');
    return null;
  } finally {
    $('#run-bench').removeAttribute('disabled');
  }
}

function downloadReports() {
  const blob = new Blob([JSON.stringify(state.reports, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `bench-${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function mount() {
  $('#app').innerHTML = `
  <header>
    <h1>seekdb 端侧迷你知识库 <small>浏览器本地向量化 · seekdb 混合检索</small></h1>
    <div class="badges">
      <span id="badge-backend" class="badge">推理后端 未加载</span>
      <span id="badge-dtype" class="badge">精度 -</span>
      <span id="badge-dim" class="badge">维度 -</span>
      <span id="badge-seekdb" class="badge">seekdb …</span>
    </div>
  </header>
  <main>
    <aside>
      <section class="card">
        <h2>模型与推理后端</h2>
        <label for="model">Embedding 模型</label>
        <select id="model">
          <option value="Xenova/bge-small-zh-v1.5">Xenova/bge-small-zh-v1.5（512 维，中文）</option>
          <option value="Xenova/all-MiniLM-L6-v2">Xenova/all-MiniLM-L6-v2（384 维，英文）</option>
        </select>
        <div class="grid2">
          <div>
            <label for="dtype">精度 / 量化</label>
            <select id="dtype">
              <option value="q8">q8 (INT8)</option>
              <option value="fp16">fp16</option>
              <option value="fp32">fp32（基线）</option>
            </select>
          </div>
          <div>
            <label for="device">推理后端</label>
            <select id="device">
              <option value="auto">自动（WebGPU 优先）</option>
              <option value="webgpu">强制 WebGPU</option>
              <option value="wasm">WASM</option>
            </select>
          </div>
        </div>
        <div class="row" style="margin-top:10px">
          <button id="load-model">加载模型</button>
          <button id="reload-model" class="ghost fixed">重新加载</button>
        </div>
        <div class="progress"><i id="model-progress"></i></div>
        <div class="meta" id="model-meta">未加载。首次使用会从模型站点下载 ONNX 权重，随后走浏览器缓存。</div>
      </section>

      <section class="card">
        <h2>知识库集合</h2>
        <div class="kb-list" id="kb-list"></div>
        <div class="row" style="margin-top:10px">
          <input id="kb-name" type="text" placeholder="新集合名，如 kb_notes" value="kb_main" />
          <button id="create-kb" class="fixed small">新建</button>
        </div>
      </section>

      <section class="card">
        <h2>导入语料</h2>
        <input id="files" type="file" multiple accept=".txt,.md,.markdown,.json,.csv,.log" />
        <div class="grid2" style="margin-top:8px">
          <div><label for="chunk-size">分块大小（字符）</label><input id="chunk-size" type="number" value="400" /></div>
          <div><label for="chunk-overlap">重叠（字符）</label><input id="chunk-overlap" type="number" value="60" /></div>
        </div>
        <div class="grid2">
          <div><label for="batch-size">批大小</label><input id="batch-size" type="number" value="16" /></div>
          <div><label>示例语料</label><button id="load-sample" class="ghost small" style="width:100%">导入 30 篇示例</button></div>
        </div>
        <div class="progress"><i id="import-progress"></i></div>
        <div class="meta" id="import-status"></div>
        <div class="meta" id="import-meta"></div>
      </section>
    </aside>

    <section>
      <div class="tabs">
        <div class="tab active" data-tab="search">检索</div>
        <div class="tab" data-tab="bench">基准测试</div>
        <div class="tab" data-tab="state">集合状态</div>
      </div>

      <div class="panel active" id="panel-search">
        <div class="card">
          <div class="search-bar">
            <input id="query" type="text" placeholder="输入问题，例如：浏览器不支持 WebGPU 时如何降级？" />
            <select id="mode">
              <option value="hybrid">混合检索（向量+全文）</option>
              <option value="vector">仅向量</option>
              <option value="fulltext">仅全文</option>
            </select>
            <input id="topk" type="number" value="8" style="width:76px;flex:0 0 auto" />
            <button id="search-btn" class="fixed">检索</button>
          </div>
          <div class="timings" id="search-timings"><span class="chip">当前集合 <b id="current-kb">未选择</b></span></div>
          <div class="results" id="results">
            <div class="empty">导入语料后在这里输入查询。混合检索由 seekdb 的 DBMS_HYBRID_SEARCH 在库内完成。</div>
          </div>
        </div>
      </div>

      <div class="panel" id="panel-bench">
        <div class="card">
          <div class="row">
            <div><label for="bench-dtype">精度</label>
              <select id="bench-dtype"><option value="q8">q8 (INT8)</option><option value="fp16">fp16</option><option value="fp32">fp32</option></select>
            </div>
            <div><label for="bench-device">后端</label>
              <select id="bench-device"><option value="auto">自动</option><option value="webgpu">WebGPU</option><option value="wasm">WASM</option></select>
            </div>
            <div style="align-self:end"><button id="run-bench" style="width:100%">运行基准测试</button></div>
            <div style="align-self:end"><button id="download-bench" class="ghost" style="width:100%">导出 JSON</button></div>
          </div>
          <div class="progress"><i id="bench-progress"></i></div>
          <div class="log" id="bench-log"></div>
          <div class="meta" id="bench-meta"></div>
          <div id="bench-report" style="margin-top:12px"><div class="empty">还没有运行基准测试</div></div>
        </div>
      </div>

      <div class="panel" id="panel-state">
        <div class="card">
          <h2>集合状态</h2>
          <div class="meta" id="docs-preview"></div>
          <div id="state-table"></div>
        </div>
      </div>
    </section>
  </main>`;

  $('#load-model').addEventListener('click', () => {
    void loadModel({
      dtype: ($('#dtype') as HTMLSelectElement).value as Dtype,
      device: ($('#device') as HTMLSelectElement).value as DeviceChoice,
    }).catch((err) => toast(err.message, 'err'));
  });
  $('#reload-model').addEventListener('click', async () => {
    state.init = null;
    await loadModel({
      dtype: ($('#dtype') as HTMLSelectElement).value as Dtype,
      device: ($('#device') as HTMLSelectElement).value as DeviceChoice,
    }).catch((err) => toast(err.message, 'err'));
  });
  $('#create-kb').addEventListener('click', async () => {
    const name = ($('#kb-name') as HTMLInputElement).value.trim();
    if (!state.init) return toast('请先加载模型以确定向量维度', 'err');
    try {
      await api.create(name, state.dim, '', state.init.modelId);
      state.current = name;
      await refreshCollections();
      toast(`已创建 ${name}`);
    } catch (err) {
      toast((err as Error).message, 'err');
    }
  });
  $('#files').addEventListener('change', (ev) => {
    const input = ev.target as HTMLInputElement;
    if (input.files?.length) void handleFiles(input.files).catch((err) => toast(err.message, 'err'));
  });
  $('#load-sample').addEventListener('click', () => void ingestSample().catch((err) => toast(err.message, 'err')));
  $('#search-btn').addEventListener('click', () => void doSearch().catch((err) => toast(err.message, 'err')));
  $('#query').addEventListener('keydown', (ev) => {
    if ((ev as KeyboardEvent).key === 'Enter') void doSearch().catch((err) => toast(err.message, 'err'));
  });
  $('#run-bench').addEventListener('click', () => void runBenchUI());
  $('#download-bench').addEventListener('click', downloadReports);

  document.querySelectorAll<HTMLElement>('.tab').forEach((tab) =>
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach((p) => p.classList.remove('active'));
      tab.classList.add('active');
      $(`#panel-${tab.dataset.tab}`).classList.add('active');
      if (tab.dataset.tab === 'state') renderStateTable();
    }),
  );
}

function renderStateTable() {
  const box = $('#state-table');
  box.innerHTML = `<table><thead><tr><th>集合</th><th>维度</th><th>分块</th><th>模型</th><th>创建时间</th></tr></thead><tbody>${state.collections
    .map(
      (c) => `<tr><td>${escapeHtml(c.name)}</td><td class="num">${c.dimension}</td><td class="num">${c.chunks}</td><td>${escapeHtml(c.model || '-')}</td><td>${c.createdAt ? new Date(c.createdAt).toLocaleString() : '-'}</td></tr>`,
    )
    .join('')}</tbody></table>`;
}

async function boot() {
  mount();
  try {
    const cfg = await api.config();
    config.mode = cfg.mode;
    config.modelHost = cfg.modelHost || '';
    config.defaultModel = cfg.defaultModel || config.defaultModel;
    config.localModels = Boolean(cfg.localModels);
    config.localPath = cfg.localPath || '/models/';
    const savedModel = localStorage.getItem('kb.model');
    if (savedModel) ($('#model') as HTMLSelectElement).value = savedModel;
    const savedDtype = localStorage.getItem('kb.dtype');
    if (savedDtype) ($('#dtype') as HTMLSelectElement).value = savedDtype;
    else if (await detectWebGPU()) ($('#dtype') as HTMLSelectElement).value = 'fp16';
    const savedReports = localStorage.getItem('kb.reports');
    if (savedReports) {
      state.reports = JSON.parse(savedReports);
      renderBench();
    }
    state.current = localStorage.getItem('kb.current');
    await refreshCollections();
    render();
  } catch (err) {
    toast(`无法连接 seekdb 服务：${(err as Error).message}`, 'err');
  }

  // 自动加载上次使用的模型，减少重复操作。
  const autoDtype = (($('#dtype') as HTMLSelectElement).value as Dtype) || 'q8';
  const autoloadOff = new URLSearchParams(location.search).get('autoload') === '0';
  if (!autoloadOff && localStorage.getItem('kb.autoload') !== '0') {
    void loadModel({ dtype: autoDtype, device: 'auto' })
      .then(() => (localStorage.getItem('kb.reports') ? renderBench() : undefined))
      .catch((err) => toast(`模型加载失败：${err.message}`, 'err'));
  }
}

declare global {
  interface Window {
    __KB__: any;
  }
}

window.__KB__ = {
  state,
  api,
  loadModel,
  ingestSample,
  handleFiles,
  search: doSearch,
  bench: runBenchUI,
  reports: () => state.reports,
  clearReports: () => {
    state.reports = [];
    localStorage.removeItem('kb.reports');
    renderBench();
  },
};

void boot();
