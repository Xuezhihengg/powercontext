import express from 'express';
import cors from 'cors';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import {
  createCollection,
  listCollectionStats,
  deleteCollection,
  upsertDocuments,
  hybridSearch,
  upsertReviewProgress,
  updateMastery,
  getWeakPoints,
  getAllProgress,
} from './seekdb.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const app = express();
const PORT = 8787;

app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use('/models', express.static(join(__dirname, '..', 'models')));

app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok' });
});

app.post('/api/collections', async (req, res) => {
  try {
    const { courseId } = req.body;
    if (!courseId || typeof courseId !== 'string') {
      return res.status(400).json({ error: '缺少 courseId' });
    }
    await createCollection(courseId);
    res.json({ ok: true, courseId });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/api/collections', async (_req, res) => {
  try {
    res.json(await listCollectionStats());
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.delete('/api/collections/:courseId', async (req, res) => {
  try {
    await deleteCollection(req.params.courseId);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post('/api/import', async (req, res) => {
  try {
    const { courseId, chunks } = req.body;
    if (!courseId || !Array.isArray(chunks)) {
      return res.status(400).json({ error: '缺少 courseId 或 chunks' });
    }
    if (chunks.length === 0) {
      return res.json({ ok: true, imported: 0 });
    }
    const docs = chunks.map((c) => ({
      id: c.id,
      text: c.text,
      embedding: c.embedding,
      file_name: c.fileName || '',
      chunk_index: c.chunkIndex ?? 0,
    }));
    await upsertDocuments(courseId, docs);
    res.json({ ok: true, imported: docs.length });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post('/api/search', async (req, res) => {
  try {
    const { courseId, query, vector, topK } = req.body;
    if (!courseId || !query || !vector) {
      return res.status(400).json({ error: '缺少 courseId / query / vector' });
    }
    const rawResults = await hybridSearch(courseId, query, vector, topK || 10);
    const results = (Array.isArray(rawResults) ? rawResults : []).map((row) => {
      let meta = row.metadata ?? row.METADATA ?? {};
      if (typeof meta === 'string') {
        try { meta = JSON.parse(meta); } catch { meta = {}; }
      }
      return {
        id: String(row._id ?? row.id ?? ''),
        text: String(row.document ?? row.DOCUMENT ?? row.text ?? ''),
        score: Number(row._score ?? row._distance ?? row.score ?? 0),
        file_name: meta.file_name || '',
        chunk_index: meta.chunk_index ?? 0,
      };
    });
    res.json({ results });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post('/api/review/add', async (req, res) => {
  try {
    const { courseId, chunkId, text, fileName } = req.body;
    if (!courseId || !chunkId) {
      return res.status(400).json({ error: '缺少 courseId 或 chunkId' });
    }
    await upsertReviewProgress({
      id: `${courseId}::${chunkId}`,
      collection_id: courseId,
      chunk_id: chunkId,
      text,
      file_name: fileName,
    });
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post('/api/review/mastery', async (req, res) => {
  try {
    const { id, mastery } = req.body;
    if (!id || mastery === undefined) {
      return res.status(400).json({ error: '缺少 id 或 mastery' });
    }
    await updateMastery(id, mastery);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/api/review/weak/:courseId', async (req, res) => {
  try {
    const rows = await getWeakPoints(req.params.courseId, 5);
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/api/review/all/:courseId', async (req, res) => {
  try {
    const rows = await getAllProgress(req.params.courseId);
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.listen(PORT, () => {
  console.log(`StudyStack API server running on http://localhost:${PORT}`);
});
