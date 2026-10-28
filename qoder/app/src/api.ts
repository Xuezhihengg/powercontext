const API_BASE = '/api';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export interface CollectionInfo {
  courseId: string;
  collectionId: string;
  docCount: number;
  chunkCount: number;
  dimension: number;
}

export interface SearchResult {
  id: string;
  text: string;
  score: number;
  file_name?: string;
  chunk_index?: number;
  [key: string]: unknown;
}

export interface ReviewEntry {
  id: string;
  collection_id: string;
  chunk_id: string;
  text: string;
  file_name: string;
  mastery: number;
  review_count: number;
  last_reviewed: string;
}

export const api = {
  createCollection(courseId: string) {
    return request<{ ok: boolean }>('/collections', {
      method: 'POST',
      body: JSON.stringify({ courseId }),
    });
  },

  listCollections(): Promise<CollectionInfo[]> {
    return request<CollectionInfo[]>('/collections');
  },

  deleteCollection(courseId: string) {
    return request<{ ok: boolean }>(`/collections/${encodeURIComponent(courseId)}`, {
      method: 'DELETE',
    });
  },

  importChunks(courseId: string, chunks: Array<{
    id: string;
    text: string;
    embedding: number[];
    fileName: string;
    chunkIndex: number;
  }>) {
    return request<{ ok: boolean; imported: number }>('/import', {
      method: 'POST',
      body: JSON.stringify({ courseId, chunks }),
    });
  },

  search(courseId: string, query: string, vector: number[], topK = 10) {
    return request<{ results: SearchResult[] }>('/search', {
      method: 'POST',
      body: JSON.stringify({ courseId, query, vector, topK }),
    });
  },

  addReview(courseId: string, chunkId: string, text: string, fileName: string) {
    return request<{ ok: boolean }>('/review/add', {
      method: 'POST',
      body: JSON.stringify({ courseId, chunkId, text, fileName }),
    });
  },

  updateMastery(id: string, mastery: number) {
    return request<{ ok: boolean }>('/review/mastery', {
      method: 'POST',
      body: JSON.stringify({ id, mastery }),
    });
  },

  getWeakPoints(courseId: string): Promise<ReviewEntry[]> {
    return request<ReviewEntry[]>(`/review/weak/${encodeURIComponent(courseId)}`);
  },

  getAllProgress(courseId: string): Promise<ReviewEntry[]> {
    return request<ReviewEntry[]>(`/review/all/${encodeURIComponent(courseId)}`);
  },
};
