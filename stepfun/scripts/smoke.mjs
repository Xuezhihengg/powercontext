#!/usr/bin/env node
/**
 * Data-layer smoke test against a running API (npm run dev / npm start).
 * Verifies: collection lifecycle, incremental write, index refresh visibility,
 * hybrid retrieval, vector/fulltext separation and collection isolation.
 */
const base = process.env.API_BASE || 'http://127.0.0.1:8787/api';

const vec = (v) => {
  const n = Math.hypot(...v);
  return v.map((x) => Math.round((x / n) * 1e6) / 1e6);
};
const DIM = 6;

async function call(method, path, body) {
  const res = await fetch(base + path, {
    method,
    headers: { 'content-type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json();
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status} ${json.error}`);
  return json;
}

let failures = 0;
function check(name, ok, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`);
  if (!ok) failures++;
}

const name = `smoke_${Date.now().toString(36)}`;
await call('POST', '/collections', { name, dimension: DIM, description: 'smoke' });

const first = [
  { id: 'a1', text: 'seekdb 向量数据库支持混合检索与全文索引', v: vec([1, 0, 0, 0, 0, 0]) },
  { id: 'a2', text: '浏览器端使用 WebGPU 或 WASM 做本地推理', v: vec([0, 1, 0, 0, 0, 0]) },
];
const add1 = await call('POST', `/collections/${name}/docs`, {
  dimension: DIM,
  model: 'smoke',
  items: first.map((d) => ({ id: d.id, text: d.text, vector: d.v, metadata: { docId: d.id, title: d.id, source: 'smoke', chunk: 0 } })),
});
check('首次写入并刷新索引', add1.inserted === 2 && add1.refreshed === true, `write=${add1.writeMs}ms refresh=${add1.refreshMs}ms`);

const q1 = await call('POST', `/collections/${name}/search`, {
  query: '向量数据库', vector: vec([0.95, 0.05, 0, 0, 0, 0]), k: 3, mode: 'hybrid',
});
check('混合检索命中已写入文档', q1.hits[0]?.id === 'a1', JSON.stringify(q1.hits.map((h) => h.id)));

const add2 = await call('POST', `/collections/${name}/docs`, {
  dimension: DIM,
  model: 'smoke',
  items: [{ id: 'a3', text: '增量导入后可立即通过索引刷新检索到新文档', vector: vec([0, 0, 1, 0, 0, 0]), metadata: { docId: 'a3', title: 'a3', source: 'smoke', chunk: 0 } }],
});
check('增量写入', add2.inserted === 1);
const q2 = await call('POST', `/collections/${name}/search`, {
  query: '增量导入 刷新', vector: vec([0, 0, 0.9, 0.1, 0, 0]), k: 3, mode: 'hybrid',
});
check('刷新后新文档可检索', q2.hits.some((h) => h.id === 'a3'), JSON.stringify(q2.hits.map((h) => h.id)));

const fts = await call('POST', `/collections/${name}/search`, { query: '浏览器', vector: vec([1, 0, 0, 0, 0, 0]), k: 3, mode: 'fulltext' });
check('仅全文检索', fts.hits.length === 1 && fts.hits[0].id === 'a2', JSON.stringify(fts.hits.map((h) => h.id)));

const knn = await call('POST', `/collections/${name}/search`, { query: '', vector: vec([0, 0, 1, 0, 0, 0]), k: 3, mode: 'vector' });
check('仅向量检索', knn.hits[0]?.id === 'a3', JSON.stringify(knn.hits.map((h) => h.id)));

const other = `smoke_iso_${Date.now().toString(36)}`;
await call('POST', '/collections', { name: other, dimension: DIM });
const iso = await call('POST', `/collections/${other}/search`, { query: 'seekdb', vector: vec([1, 0, 0, 0, 0, 0]), k: 3, mode: 'hybrid' });
check('集合隔离：新集合不返回其它集合数据', iso.hits.length === 0);

const list = await call('GET', '/collections');
const entry = list.collections.find((c) => c.name === name);
check('集合状态统计', entry?.chunks === 3 && entry?.docs === 3, JSON.stringify(entry));

await call('DELETE', `/collections/${name}`);
await call('DELETE', `/collections/${other}`);
const after = await call('GET', '/collections');
check('删除集合', !after.collections.some((c) => c.name === name));

console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
process.exit(failures ? 1 : 0);
