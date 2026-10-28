export type Dtype = 'fp32' | 'fp16' | 'q8' | 'q4';
export type Backend = 'webgpu' | 'wasm';

export interface InitResult {
  backend: Backend;
  requestedBackend: Backend;
  fallbackReason: string;
  loadMs: number;
  warmMs: number;
  modelBytes: number;
  totalBytes: number;
  files: string[];
  dim: number;
  modelId: string;
  dtype: Dtype;
}

export interface EmbedResult {
  count: number;
  dim: number;
  ms: number;
  vectors: Float32Array;
  backend: Backend;
}

type ProgressHandler = (payload: any) => void;

export class Embedder {
  private worker: Worker;
  private seq = 0;
  private pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void; onProgress?: ProgressHandler }>();

  constructor() {
    this.worker = new Worker(new URL('./embedder.worker.ts', import.meta.url), { type: 'module' });
    this.worker.onmessage = (event: MessageEvent) => {
      const msg = event.data;
      const entry = this.pending.get(msg.id);
      if (!entry) return;
      if (msg.type === 'progress') {
        entry.onProgress?.(msg);
        return;
      }
      this.pending.delete(msg.id);
      if (msg.ok) entry.resolve(msg.payload);
      else entry.reject(new Error(msg.message || 'worker error'));
    };
    this.worker.onerror = (event) => {
      for (const [, entry] of this.pending) entry.reject(new Error(event.message || 'worker crashed'));
      this.pending.clear();
    };
  }

  private call<T>(type: string, payload: Record<string, unknown>, onProgress?: ProgressHandler, transfer: Transferable[] = []): Promise<T> {
    const id = ++this.seq;
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve, reject, onProgress });
      this.worker.postMessage({ type, id, ...payload }, transfer);
    });
  }

  init(opts: { modelId: string; dtype: Dtype; device: Backend; modelHost?: string; localModels?: boolean; localPath?: string }, onProgress?: ProgressHandler) {
    return this.call<InitResult>('init', opts, onProgress);
  }

  async embed(texts: string[], batchSize = 8, onProgress?: ProgressHandler): Promise<EmbedResult> {
    const raw = await this.call<any>('embed', { texts, batchSize }, onProgress);
    return { ...raw, vectors: new Float32Array(raw.vectors) };
  }

  dispose() {
    return this.call('dispose', {}).catch(() => undefined);
  }

  terminate() {
    this.worker.terminate();
  }
}

export async function detectWebGPU(): Promise<boolean> {
  const nav = navigator as any;
  if (!nav.gpu) return false;
  try {
    const adapter = await nav.gpu.requestAdapter();
    return Boolean(adapter);
  } catch {
    return false;
  }
}
