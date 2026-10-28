import fs from 'node:fs';
import path from 'node:path';
import {
  SeekdbClient,
  Schema,
  FulltextIndexConfig,
  VectorIndexConfig,
} from 'seekdb';

const NAME_RE = /^[a-z][a-z0-9_]{1,39}$/;

export function isValidName(name) {
  return typeof name === 'string' && NAME_RE.test(name);
}

/** Keep only CJK / letters / digits / spaces so the full-text query parser never sees operators. */
export function sanitizeFulltextQuery(query) {
  return String(query || '')
    .replace(/[^\p{Script=Han}\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export class KbStore {
  constructor(options = {}) {
    const useEmbedded = Boolean(options.path);
    this.mode = useEmbedded ? 'embedded' : 'server';
    const args = useEmbedded
      ? { path: options.path }
      : {
          host: options.host || '127.0.0.1',
          port: Number(options.port || 2881),
          user: options.user || 'root',
          password: options.password || '',
          database: options.database || 'test',
        };
    this.client = new SeekdbClient(args);
    this.registryFile = options.registryFile;
    this.exactVector = options.exactVector !== false;
    this.registry = this.#loadRegistry();
    this.collections = new Map();
  }

  #loadRegistry() {
    if (!this.registryFile || !fs.existsSync(this.registryFile)) return {};
    try {
      return JSON.parse(fs.readFileSync(this.registryFile, 'utf8'));
    } catch {
      return {};
    }
  }

  #saveRegistry() {
    if (!this.registryFile) return;
    fs.mkdirSync(path.dirname(this.registryFile), { recursive: true });
    fs.writeFileSync(this.registryFile, JSON.stringify(this.registry, null, 2));
  }

  async close() {
    await this.client.close();
  }

  schemaFor(dimension) {
    return new Schema({
      fulltextIndex: new FulltextIndexConfig('ngram', { ngram_token_size: 2 }),
      vectorIndex: new VectorIndexConfig({
        hnsw: { dimension, distance: 'cosine' },
        embeddingFunction: null,
      }),
    });
  }

  async ensureCollection(name, dimension, meta = {}) {
    if (!isValidName(name)) {
      throw Object.assign(new Error('集合名只能包含小写字母、数字、下划线，且以字母开头（2-40 字符）'), { status: 400 });
    }
    const cached = this.collections.get(name);
    if (cached) return cached;

    const exists = await this.client.hasCollection(name);
    if (exists) {
      const col = await this.client.getCollection({ name, embeddingFunction: null });
      if (dimension && col.dimension !== dimension) {
        throw Object.assign(
          new Error(`集合 ${name} 现有向量维度为 ${col.dimension}，与当前模型维度 ${dimension} 不一致，请新建集合或切换模型`),
          { status: 409 },
        );
      }
      this.collections.set(name, col);
      return col;
    }

    const schema = this.schemaFor(dimension);
    const col = await this.client.createCollection({
      name,
      schema,
      embeddingFunction: null,
    });
    this.collections.set(name, col);
    this.registry[name] = {
      name,
      dimension,
      description: meta.description || '',
      model: meta.model || '',
      createdAt: Date.now(),
      docs: 0,
      chunks: 0,
    };
    this.#saveRegistry();
    return col;
  }

  async getCollection(name) {
    const cached = this.collections.get(name);
    if (cached) return cached;
    const col = await this.client.getCollection({ name, embeddingFunction: null });
    this.collections.set(name, col);
    return col;
  }

  async listCollections() {
    const names = await this.client.listCollections({ withEmbeddingFunction: false });
    const out = [];
    for (const col of names) {
      const info = this.registry[col.name] || {};
      const chunks = await col.count();
      out.push({
        name: col.name,
        dimension: col.dimension,
        distance: col.distance,
        chunks,
        docs: info.docs ?? null,
        description: info.description ?? '',
        model: info.model ?? '',
        createdAt: info.createdAt ?? null,
      });
    }
    return out;
  }

  async dropCollection(name) {
    await this.client.deleteCollection(name);
    this.collections.delete(name);
    delete this.registry[name];
    this.#saveRegistry();
  }

  async addDocuments(name, items, dimension, model = '') {
    const col = await this.ensureCollection(name, dimension, { model });
    const t0 = performance.now();
    await col.upsert({
      ids: items.map((item) => item.id),
      embeddings: items.map((item) => item.vector),
      documents: items.map((item) => item.text),
      metadatas: items.map((item) => item.metadata || {}),
    });
    const writeMs = performance.now() - t0;

    const t1 = performance.now();
    let refreshed = true;
    try {
      await col.refresh_index();
    } catch (err) {
      refreshed = false;
      console.warn('[seekdb] refresh_index failed:', err?.message || err);
    }
    const refreshMs = performance.now() - t1;

    const entry = this.registry[name] || { name, dimension, docs: 0, chunks: 0 };
    const docIds = new Set(entry.docIds || []);
    for (const item of items) docIds.add(String(item.metadata?.docId || item.id));
    entry.docIds = [...docIds];
    entry.docs = docIds.size;
    entry.chunks = await col.count();
    if (model) entry.model = model;
    this.registry[name] = entry;
    this.#saveRegistry();

    return {
      inserted: items.length,
      writeMs: round(writeMs),
      refreshMs: round(refreshMs),
      refreshed,
      total: entry.chunks,
    };
  }

  /**
   * Hybrid / fulltext search executed inside seekdb through DBMS_HYBRID_SEARCH.
   *
   * The SDK generates a single SQL statement that does keyword MATCH + vector
   * distance + RRF fusion in the database. In the embedded (native bindings)
   * build the ANN index is not queryable yet, so the APPROXIMATE hint is
   * removed and seekdb falls back to an exact vector scan inside the same
   * statement. Fusion still happens in the database, never in the client.
   */
  async dbHybridSearch(col, { text, vector, k }) {
    const table = col.collectionId ? `c$v2$${col.collectionId}` : col.name;
    const parm = {};
    if (text) {
      parm.query = { query_string: { fields: ['document'], query: text } };
    }
    if (vector) {
      parm.knn = { field: 'embedding', k: Math.max(k * 4, 40), query_vector: vector };
    }
    parm.rank = { rrf: { rank_window_size: 64, rank_constant: 60 } };
    parm.size = k;

    await this.client.execute('SET @search_parm = ?', [JSON.stringify(parm)]);
    const rows = await this.client.execute(
      `SELECT DBMS_HYBRID_SEARCH.GET_SQL('${table}', @search_parm) as q FROM dual`,
    );
    const raw = rows?.[0]?.q;
    if (!raw) return [];
    let sql = String(raw).trim().replace(/^['"]|['"]$/g, '');
    if (this.exactVector) sql = sql.replace(/\bAPPROXIMATE\b/gi, '');
    if (!/^SELECT\s/i.test(sql)) throw new Error('seekdb 返回了非法的混合检索 SQL');
    return (await this.client.execute(sql)) || [];
  }

  async search(name, { query, vector, k = 8, mode = 'hybrid' }) {
    const col = await this.getCollection(name);
    const anchor = Array.isArray(vector) && vector.length ? vector : null;
    const textQuery = sanitizeFulltextQuery(query);

    if (mode !== 'vector' && !anchor && !textQuery) {
      throw Object.assign(new Error('缺少查询条件：请提供查询文本或查询向量'), { status: 400 });
    }

    const t0 = performance.now();
    let rows = [];
    let engine;
    let fulltextSkipped = false;

    if (mode === 'vector') {
      engine = this.exactVector
        ? 'seekdb SQL 精确向量扫描 (cosine)'
        : 'seekdb collection.query (HNSW)';
      const res = await col.query({
        queryEmbeddings: [anchor],
        nResults: k,
        include: ['documents', 'metadatas', 'distances'],
        approximate: !this.exactVector,
      });
      const ids = res?.ids?.[0] ?? [];
      const documents = res?.documents?.[0] ?? [];
      const metadatas = res?.metadatas?.[0] ?? [];
      const distances = res?.distances?.[0] ?? [];
      rows = ids.map((id, i) => ({
        _id: id,
        document: documents[i],
        metadata: metadatas[i],
        _distance: distances[i],
      }));
    } else if (mode === 'fulltext') {
      if (!textQuery) throw Object.assign(new Error('全文检索需要非空查询文本'), { status: 400 });
      engine = 'DBMS_HYBRID_SEARCH（仅全文，库内 MATCH）';
      rows = await this.dbHybridSearch(col, { text: textQuery, vector: null, k });
    } else {
      engine = this.exactVector
        ? 'DBMS_HYBRID_SEARCH（库内 RRF：全文 + 精确向量）'
        : 'DBMS_HYBRID_SEARCH（库内 RRF：全文 + HNSW）';
      fulltextSkipped = !textQuery;
      rows = await this.dbHybridSearch(col, { text: textQuery, vector: anchor, k });
    }
    const tookMs = performance.now() - t0;

    const hits = rows.map((row) => {
      let meta = row.metadata ?? row.METADATA ?? {};
      if (typeof meta === 'string') {
        try { meta = JSON.parse(meta); } catch { meta = {}; }
      }
      const score = row._score ?? row._distance ?? row.distance ?? null;
      return {
        id: String(row._id ?? row.id),
        docId: meta.docId ?? null,
        title: meta.title ?? '',
        source: meta.source ?? '',
        chunk: meta.chunk ?? 0,
        text: String(row.document ?? ''),
        score: score == null ? null : Number(score),
      };
    });

    return {
      tookMs: round(tookMs),
      engine,
      mode,
      fulltextSkipped,
      fulltextQuery: textQuery,
      exactVector: this.exactVector,
      hits,
    };
  }

  async getDocuments(name, limit = 50) {
    const col = await this.getCollection(name);
    const res = await col.get({ limit, include: ['documents', 'metadatas'] });
    return (res.ids || []).map((id, i) => ({
      id: String(id),
      text: res.documents?.[i] ?? '',
      metadata: res.metadatas?.[i] ?? {},
    }));
  }
}

function round(value) {
  return Math.round(value * 100) / 100;
}
