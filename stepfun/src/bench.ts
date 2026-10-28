import type { Embedder, InitResult, Dtype, Backend } from './embedder';
import type { api } from './api';
import { chunkText } from './chunker';

export interface CornerDoc {
  id: string;
  title: string;
  text: string;
}

export interface BenchQuery {
  id: string;
  query: string;
  relevant: string[];
}

export interface StageTimings {
  modelLoadMs: number;
  modelWarmMs: number;
  docEmbedMs: number;
  docEmbedFirstMs: number;
  writeMs: number;
  refreshMs: number;
  queryEmbedMedianMs: number;
  searchMedianMs: number;
  e2eMedianMs: number;
}

export interface Quality {
  recallAt5: number;
  ndcgAt5: number;
  mrrAt10: number;
  perQuery: { id: string; recall: number; ndcg: number; rank: number }[];
}

export interface BenchReport {
  timestamp: string;
  model: string;
  dtype: Dtype;
  backend: Backend;
  fallbackReason: string;
  modelBytes: number;
  totalBytes: number;
  dim: number;
  docs: number;
  chunks: number;
  corpusChars: number;
  docThroughputCharsPerSec: number;
  timings: StageTimings;
  quality: Quality;
  collection: string;
  userAgent: string;
}

export interface BenchOptions {
  dtype: Dtype;
  device: Backend | 'auto';
  api: typeof api;
  corpus: CornerDoc[];
  queries: BenchQuery[];
  loadModel: (cfg: { dtype: Dtype; device: Backend | 'auto' }) => Promise<{ init: InitResult; embedder: Embedder }>;
  onProgress: (message: string, percent?: number) => void;
}

export function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return Math.round((sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2) * 100) / 100;
}

function ndcgAtK(ranked: string[], relevant: Set<string>, k: number): number {
  let dcg = 0;
  for (let i = 0; i < Math.min(k, ranked.length); i++) {
    if (relevant.has(ranked[i])) dcg += 1 / Math.log2(i + 2);
  }
  const ideal = [...relevant].slice(0, k).reduce((sum, _, i) => sum + 1 / Math.log2(i + 2), 0);
  return ideal ? dcg / ideal : 0;
}

export async function runBench(options: BenchOptions): Promise<BenchReport> {
  const { dtype, device, api, corpus, queries, loadModel, onProgress } = options;

  onProgress('加载模型', 5);
  const { init, embedder } = await loadModel({ dtype, device });

  const chunks: { id: string; docId: string; title: string; text: string; chunk: number }[] = [];
  for (const doc of corpus) {
    const parts = chunkText(doc.text, { maxChars: 240, overlap: 40 });
    parts.forEach((part, index) => {
      chunks.push({ id: `${doc.id}-${index}`, docId: doc.id, title: doc.title, text: part.text, chunk: index });
    });
  }

  onProgress(`向量化 ${chunks.length} 个分块`, 15);
  const embedStart = performance.now();
  const docResult = await embedder.embed(chunks.map((c) => c.text), 16, (msg) => {
    if (msg.stage === 'embed') onProgress(`向量化 ${msg.done}/${msg.total}`, 15 + (msg.done / msg.total) * 45);
  });
  const docEmbedFirstMs = performance.now() - embedStart;
  const docEmbedRuns = [docEmbedFirstMs];
  for (let i = 0; i < 2; i++) {
    const r = await embedder.embed(chunks.map((c) => c.text), 16);
    docEmbedRuns.push(r.ms);
  }
  const docEmbedMs = median(docEmbedRuns);

  const collection = `bench_${dtype}_${init.backend}`;
  try { await api.drop(collection); } catch { /* ignore */ }
  await api.create(collection, docResult.dim, `bench ${dtype} ${init.backend}`, init.modelId);

  onProgress('写入 seekdb 并刷新索引', 65);
  const vectors = docResult.vectors;
  const dim = docResult.dim;
  const items = chunks.map((chunk, i) => ({
    id: chunk.id,
    text: chunk.text,
    vector: Array.from(vectors.subarray(i * dim, (i + 1) * dim)),
    metadata: {
      docId: chunk.docId,
      title: chunk.title,
      source: 'bench',
      chunk: chunk.chunk,
      createdAt: Date.now(),
    },
  }));
  const writeStart = performance.now();
  const write = await api.addDocs(collection, { items, dimension: dim, model: init.modelId });
  const writeAndRefreshMs = performance.now() - writeStart;

  const perQuery: { id: string; recall: number; ndcg: number; rank: number }[] = [];
  const queryEmbedMs: number[] = [];
  const searchMs: number[] = [];
  const e2eMs: number[] = [];

  for (let qi = 0; qi < queries.length; qi++) {
    const q = queries[qi];
    onProgress(`查询 ${qi + 1}/${queries.length}`, 70 + (qi / queries.length) * 25);
    const t0 = performance.now();
    const qv = await embedder.embed([q.query], 1);
    const t1 = performance.now();
    const res = await api.search(collection, {
      query: q.query,
      vector: Array.from(qv.vectors.subarray(0, qv.dim)),
      k: 10,
      mode: 'hybrid',
    });
    const t2 = performance.now();
    queryEmbedMs.push(t1 - t0);
    searchMs.push(res.tookMs);
    e2eMs.push(t2 - t0);

    const rankedDocs = res.hits.map((h) => String(h.docId || h.id.split('-')[0]));
    const relevant = new Set(q.relevant);
    const top5 = rankedDocs.slice(0, 5);
    const hit = top5.filter((d) => relevant.has(d)).length;
    const firstIndex = rankedDocs.findIndex((d) => relevant.has(d));
    perQuery.push({
      id: q.id,
      recall: relevant.size ? hit / relevant.size : 0,
      ndcg: ndcgAtK(rankedDocs, relevant, 5),
      rank: firstIndex < 0 ? 0 : firstIndex + 1,
    });
  }

  const quality: Quality = {
    recallAt5: Math.round((perQuery.reduce((s, q) => s + q.recall, 0) / perQuery.length) * 1000) / 1000,
    ndcgAt5: Math.round((perQuery.reduce((s, q) => s + q.ndcg, 0) / perQuery.length) * 1000) / 1000,
    mrrAt10: Math.round((perQuery.reduce((s, q) => s + (q.rank ? 1 / q.rank : 0), 0) / perQuery.length) * 1000) / 1000,
    perQuery,
  };

  const corpusChars = corpus.reduce((s, d) => s + d.text.length, 0);
  onProgress('完成', 100);

  return {
    timestamp: new Date().toISOString(),
    model: init.modelId,
    dtype,
    backend: init.backend,
    fallbackReason: init.fallbackReason,
    modelBytes: init.modelBytes,
    totalBytes: init.totalBytes,
    dim,
    docs: corpus.length,
    chunks: chunks.length,
    corpusChars,
    docThroughputCharsPerSec: Math.round(corpusChars / (docEmbedMs / 1000)),
    timings: {
      modelLoadMs: init.loadMs,
      modelWarmMs: init.warmMs,
      docEmbedMs: Math.round(docEmbedMs * 100) / 100,
      docEmbedFirstMs: Math.round(docEmbedFirstMs * 100) / 100,
      writeMs: write.writeMs,
      refreshMs: write.refreshMs,
      queryEmbedMedianMs: median(queryEmbedMs),
      searchMedianMs: median(searchMs),
      e2eMedianMs: median(e2eMs),
    },
    quality,
    collection,
    userAgent: navigator.userAgent,
  };
}
