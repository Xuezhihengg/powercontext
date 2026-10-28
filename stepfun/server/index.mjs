import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';
import { KbStore } from './kb.mjs';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const dataDir = process.env.SEEKB_DATA_DIR || path.join(root, 'data');
fs.mkdirSync(dataDir, { recursive: true });

const store = new KbStore({
  path: process.env.SEEKB_PATH || path.join(dataDir, 'kb.db'),
  host: process.env.SEEKB_HOST,
  port: process.env.SEEKB_PORT,
  user: process.env.SEEKB_USER,
  password: process.env.SEEKB_PASSWORD,
  database: process.env.SEEKB_DATABASE,
  registryFile: path.join(dataDir, 'collections.json'),
  exactVector: process.env.SEEKB_APPROXIMATE !== '1',
});

const app = express();
app.use(express.json({ limit: '64mb' }));

const wrap = (handler) => (req, res, next) => Promise.resolve(handler(req, res, next)).catch(next);

app.get('/api/health', (_req, res) => {
  res.json({
    ok: true,
    mode: store.mode,
    pid: process.pid,
    time: Date.now(),
    seekdb: store.mode === 'embedded' ? 'embedded' : 'server',
  });
});

app.get('/api/collections', wrap(async (_req, res) => {
  res.json({ collections: await store.listCollections() });
}));

app.post('/api/collections', wrap(async (req, res) => {
  const { name, dimension, description = '', model = '' } = req.body || {};
  if (!dimension) throw Object.assign(new Error('缺少 dimension'), { status: 400 });
  await store.ensureCollection(name, Number(dimension), { description, model });
  res.json({ ok: true, collections: await store.listCollections() });
}));

app.delete('/api/collections/:name', wrap(async (req, res) => {
  try {
    await store.dropCollection(req.params.name);
  } catch (err) {
    if (/not found/i.test(err?.message || '')) {
      return res.json({ ok: true, dropped: false, collections: await store.listCollections() });
    }
    throw err;
  }
  res.json({ ok: true, dropped: true, collections: await store.listCollections() });
}));

app.post('/api/collections/:name/docs', wrap(async (req, res) => {
  const { items, dimension, model } = req.body || {};
  if (!Array.isArray(items) || items.length === 0) {
    throw Object.assign(new Error('items 不能为空'), { status: 400 });
  }
  const result = await store.addDocuments(req.params.name, items, Number(dimension), model);
  res.json({ ok: true, ...result });
}));

app.get('/api/collections/:name/docs', wrap(async (req, res) => {
  const limit = Math.min(Number(req.query.limit || 50), 500);
  res.json({ docs: await store.getDocuments(req.params.name, limit) });
}));

app.post('/api/collections/:name/search', wrap(async (req, res) => {
  const { query = '', vector, k = 8, mode = 'hybrid' } = req.body || {};
  res.json(await store.search(req.params.name, { query, vector, k, mode }));
}));

const modelsDir = path.join(root, 'models');
const defaultModel = process.env.DEFAULT_MODEL || 'Xenova/bge-small-zh-v1.5';
app.use('/models', express.static(modelsDir, { fallthrough: true }));

app.get('/api/config', (_req, res) => {
  res.json({
    localModels: fs.existsSync(path.join(modelsDir, defaultModel, 'config.json')),
    localPath: '/models/',
    mode: store.mode,
    seekdbPath: process.env.SEEKB_PATH || path.join(dataDir, 'kb.db'),
    modelHost: process.env.MODEL_HOST || '',
    defaultModel,
  });
});

const dist = path.join(root, 'dist');
if (fs.existsSync(dist)) {
  app.use(express.static(dist));
  app.get(/^(?!\/api).*/, (_req, res) => res.sendFile(path.join(dist, 'index.html')));
}

app.use((err, _req, res, _next) => {
  const status = err?.status || 500;
  if (status >= 500) console.error('[api]', err);
  res.status(status).json({ error: err?.message || String(err) });
});

const port = Number(process.env.PORT || 8787);
const server = app.listen(port, '127.0.0.1', () => {
  console.log(`[stepfun] seekdb ${store.mode} mode, API on http://127.0.0.1:${port}`);
  console.log(`[stepfun] data dir: ${dataDir}`);
});

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, async () => {
    server.close();
    try { await store.close(); } catch {}
    process.exit(0);
  });
}
