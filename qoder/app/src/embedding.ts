let worker: Worker | null = null;
let pendingCalls = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
let callId = 0;

export interface ModelMeta {
  backend: string;
  modelSizeBytes: number;
  loadTimeMs: number;
  dtype: string;
}

let modelMeta: ModelMeta | null = null;

function getWorker(): Worker {
  if (!worker) {
    worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
    worker.onmessage = (e: MessageEvent) => {
      const { id, error } = e.data;
      const pending = pendingCalls.get(id);
      if (!pending) return;
      pendingCalls.delete(id);
      if (error) {
        pending.reject(new Error(error));
      } else {
        if (e.data.backend) {
          modelMeta = {
            backend: e.data.backend,
            modelSizeBytes: e.data.modelSizeBytes ?? 0,
            loadTimeMs: e.data.loadTimeMs ?? 0,
            dtype: e.data.dtype ?? 'q8',
          };
        }
        pending.resolve(e.data);
      }
    };
    worker.onerror = (e) => {
      console.error('Worker error:', e);
    };
  }
  return worker;
}

function call<T>(data: Record<string, unknown>): Promise<T> {
  return new Promise((resolve, reject) => {
    const id = ++callId;
    pendingCalls.set(id, {
      resolve: (v) => resolve(v as T),
      reject,
    });
    getWorker().postMessage({ id, ...data });
  });
}

export async function ensureModelReady(): Promise<ModelMeta> {
  const result = await call<{ ready: boolean; backend: string; modelSizeBytes: number; loadTimeMs: number; dtype: string }>({ type: 'ready' });
  if (!modelMeta) {
    modelMeta = {
      backend: result.backend ?? 'unknown',
      modelSizeBytes: result.modelSizeBytes ?? 0,
      loadTimeMs: result.loadTimeMs ?? 0,
      dtype: result.dtype ?? 'q8',
    };
  }
  return modelMeta;
}

export function getModelMeta(): ModelMeta | null {
  return modelMeta;
}

export async function embedTexts(texts: string[]): Promise<number[][]> {
  const result = await call<{ results: number[][] }>({ type: 'embed', texts });
  return result.results;
}

export async function embedSingle(text: string): Promise<number[]> {
  const results = await embedTexts([text]);
  return results[0];
}
