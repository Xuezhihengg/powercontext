import {
  SeekdbClient,
  Schema,
  FulltextIndexConfig,
  VectorIndexConfig,
} from 'seekdb';

const DB_PATH = process.env.SEEKB_PATH || './data/study.db';

let client;
const collectionCache = new Map();

function getClient() {
  if (!client) {
    client = new SeekdbClient({ path: DB_PATH });
  }
  return client;
}

function buildSchema() {
  return new Schema({
    fulltextIndex: new FulltextIndexConfig('ngram', { ngram_token_size: 2 }),
    vectorIndex: new VectorIndexConfig({
      hnsw: { dimension: 512, distance: 'cosine' },
      embeddingFunction: null,
    }),
  });
}

async function _createCollection(courseId) {
  const c = getClient();
  const col = await c.createCollection({
    name: courseId,
    schema: buildSchema(),
    embeddingFunction: null,
  });
  collectionCache.set(courseId, col);
  return col;
}

async function _getCollection(courseId) {
  const cached = collectionCache.get(courseId);
  if (cached) return cached;
  const c = getClient();
  const col = await c.getCollection({ name: courseId, embeddingFunction: null });
  collectionCache.set(courseId, col);
  return col;
}

async function _hasCollection(courseId) {
  const c = getClient();
  return await c.hasCollection(courseId);
}

async function _listCollections() {
  const c = getClient();
  const list = await c.listCollections({ withEmbeddingFunction: false });
  return list || [];
}

async function _deleteCollection(courseId) {
  const c = getClient();
  await c.deleteCollection(courseId);
  collectionCache.delete(courseId);
}

async function _upsertDocuments(courseId, docs) {
  const col = await _getCollection(courseId);
  await col.upsert({
    ids: docs.map((d) => d.id),
    embeddings: docs.map((d) => d.embedding),
    documents: docs.map((d) => d.text),
    metadatas: docs.map((d) => ({
      file_name: d.file_name || '',
      chunk_index: d.chunk_index ?? 0,
    })),
  });
  await col.refresh_index();
}

function sanitizeFulltextQuery(query) {
  return String(query || '')
    .replace(/[^\p{Script=Han}\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

async function _hybridSearch(courseId, queryText, queryVector, topK = 10) {
  const c = getClient();
  const col = await _getCollection(courseId);
  const table = col.collectionId ? `c$v2$${col.collectionId}` : courseId;

  const parm = {};
  const cleanText = sanitizeFulltextQuery(queryText);
  if (cleanText) {
    parm.query = { query_string: { fields: ['document'], query: cleanText } };
  }
  if (queryVector && queryVector.length === 512) {
    parm.knn = { field: 'embedding', k: Math.max(topK * 4, 40), query_vector: queryVector };
  }
  parm.rank = { rrf: { rank_window_size: 64, rank_constant: 60 } };
  parm.size = topK;

  await c.execute('SET @search_parm = ?', [JSON.stringify(parm)]);
  const rows = await c.execute(
    `SELECT DBMS_HYBRID_SEARCH.GET_SQL('${table}', @search_parm) as q FROM dual`
  );
  const raw = rows?.[0]?.q;
  if (!raw) return [];
  let sql = String(raw).trim().replace(/^['"]|['"]$/g, '');
  sql = sql.replace(/\bAPPROXIMATE\b/gi, '');
  if (!/^SELECT\s/i.test(sql)) throw new Error('seekdb 返回了非法的混合检索 SQL');
  const results = await c.execute(sql);
  return results || [];
}

async function _ensureReviewTable() {
  const c = getClient();
  await c.execute(`
    CREATE TABLE IF NOT EXISTS review_progress (
      id VARCHAR(255) PRIMARY KEY,
      collection_id VARCHAR(255) NOT NULL,
      chunk_id VARCHAR(255) NOT NULL,
      text TEXT,
      file_name VARCHAR(512),
      mastery INTEGER DEFAULT 0,
      review_count INTEGER DEFAULT 0,
      last_reviewed DATETIME DEFAULT CURRENT_TIMESTAMP
    )
  `);
}

async function _upsertReviewProgress(entry) {
  const c = getClient();
  await _ensureReviewTable();
  const { id, collection_id, chunk_id, text, file_name } = entry;
  await c.execute(
    `INSERT INTO review_progress (id, collection_id, chunk_id, text, file_name, mastery, review_count, last_reviewed)
     VALUES (?, ?, ?, ?, ?, 0, 0, CURRENT_TIMESTAMP)
     ON DUPLICATE KEY UPDATE last_reviewed = CURRENT_TIMESTAMP`,
    [id, collection_id, chunk_id, text || '', file_name || '']
  );
}

async function _updateMastery(id, mastery) {
  const c = getClient();
  await _ensureReviewTable();
  await c.execute(
    `UPDATE review_progress SET mastery = ?, review_count = review_count + 1, last_reviewed = CURRENT_TIMESTAMP WHERE id = ?`,
    [mastery, id]
  );
}

async function _getWeakPoints(courseId, limit = 5) {
  const c = getClient();
  await _ensureReviewTable();
  const rows = await c.execute(
    `SELECT * FROM review_progress WHERE collection_id = ? ORDER BY mastery ASC, review_count DESC LIMIT ?`,
    [courseId, limit]
  );
  return rows || [];
}

async function _getAllProgress(courseId) {
  const c = getClient();
  await _ensureReviewTable();
  const rows = await c.execute(
    `SELECT * FROM review_progress WHERE collection_id = ? ORDER BY last_reviewed DESC`,
    [courseId]
  );
  return rows || [];
}

async function _listCollectionStats() {
  const c = getClient();
  const list = await c.listCollections({ withEmbeddingFunction: false });
  const out = [];
  for (const col of list || []) {
    const name = col.name || col;
    let chunkCount = 0;
    try { chunkCount = await col.count(); } catch { /* empty collection */ }
    out.push({
      courseId: name,
      collectionId: col.collectionId || name,
      docCount: chunkCount,
      chunkCount,
      dimension: col.dimension || 512,
    });
  }
  return out;
}

// seekdb 的原生绑定不支持并发调用，并发请求会导致进程直接退出。
// 所有数据库操作统一排队，串行执行。
let dbQueue = Promise.resolve();

function withDbLock(task) {
  const run = dbQueue.then(task, task);
  dbQueue = run.then(() => undefined, () => undefined);
  return run;
}

export const createCollection = (courseId) => withDbLock(() => _createCollection(courseId));
export const getCollection = (courseId) => withDbLock(() => _getCollection(courseId));
export const hasCollection = (courseId) => withDbLock(() => _hasCollection(courseId));
export const listCollections = () => withDbLock(() => _listCollections());
export const listCollectionStats = () => withDbLock(() => _listCollectionStats());
export const deleteCollection = (courseId) => withDbLock(() => _deleteCollection(courseId));
export const upsertDocuments = (courseId, docs) => withDbLock(() => _upsertDocuments(courseId, docs));
export const hybridSearch = (courseId, q, v, topK) => withDbLock(() => _hybridSearch(courseId, q, v, topK));
export const upsertReviewProgress = (entry) => withDbLock(() => _upsertReviewProgress(entry));
export const updateMastery = (id, mastery) => withDbLock(() => _updateMastery(id, mastery));
export const getWeakPoints = (courseId, limit) => withDbLock(() => _getWeakPoints(courseId, limit));
export const getAllProgress = (courseId) => withDbLock(() => _getAllProgress(courseId));
export const ensureReviewTable = () => withDbLock(() => _ensureReviewTable());
