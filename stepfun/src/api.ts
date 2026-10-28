export interface CollectionInfo {
  name: string;
  dimension: number;
  distance: string;
  chunks: number;
  docs: number | null;
  description: string;
  model: string;
  createdAt: number | null;
}

export interface Hit {
  id: string;
  docId: string | null;
  title: string;
  source: string;
  chunk: number;
  text: string;
  score: number | null;
}

export interface SearchResponse {
  tookMs: number;
  engine: string;
  mode: string;
  fulltextSkipped: boolean;
  fulltextQuery: string;
  hits: Hit[];
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'content-type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ ok: boolean; mode: string }>('/api/health'),
  config: () => request<{ mode: string; defaultModel: string; modelHost: string; localModels: boolean; localPath: string }>('/api/config'),
  list: () => request<{ collections: CollectionInfo[] }>('/api/collections'),
  create: (name: string, dimension: number, description = '', model = '') =>
    request<{ ok: boolean; collections: CollectionInfo[] }>('/api/collections', {
      method: 'POST',
      body: JSON.stringify({ name, dimension, description, model }),
    }),
  drop: (name: string) =>
    request<{ collections: CollectionInfo[] }>(`/api/collections/${name}`, { method: 'DELETE' }),
  addDocs: (
    name: string,
    payload: { items: unknown[]; dimension: number; model: string },
  ) =>
    request<{ inserted: number; writeMs: number; refreshMs: number; refreshed: boolean; total: number }>(
      `/api/collections/${name}/docs`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  search: (name: string, payload: { query: string; vector?: number[]; k: number; mode: string }) =>
    request<SearchResponse>(`/api/collections/${name}/search`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  docs: (name: string, limit = 50) =>
    request<{ docs: { id: string; text: string; metadata: any }[] }>(
      `/api/collections/${name}/docs?limit=${limit}`,
    ),
};
