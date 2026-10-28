/// <reference lib="webworker" />
import { env, pipeline } from '@huggingface/transformers';
import type { FeatureExtractionPipeline } from '@huggingface/transformers';

type Dtype = 'fp32' | 'fp16' | 'q8' | 'q4';

interface InitMessage {
  type: 'init';
  id: number;
  modelId: string;
  dtype: Dtype;
  device: 'webgpu' | 'wasm';
  modelHost?: string;
  localModels?: boolean;
  localPath?: string;
}

interface EmbedMessage {
  type: 'embed';
  id: number;
  texts: string[];
  batchSize: number;
}

type Incoming = InitMessage | EmbedMessage | { type: 'dispose'; id: number };

const ctx = self as unknown as DedicatedWorkerGlobalScope;

env.allowLocalModels = false;
env.useBrowserCache = true;

let extractor: FeatureExtractionPipeline | null = null;
let activeDevice: 'webgpu' | 'wasm' = 'wasm';

const fileBytes = new Map<string, number>();

function post(id: number, payload: unknown) {
  ctx.postMessage({ type: 'result', id, ok: true, payload });
}

function fail(id: number, err: unknown) {
  const e = err as Error;
  ctx.postMessage({ type: 'error', id, ok: false, message: e?.message || String(err), stack: e?.stack || '' });
}

async function loadModel(msg: InitMessage) {
  if (msg.localModels) {
    env.allowLocalModels = true;
    env.allowRemoteModels = false;
    env.localModelPath = msg.localPath || '/models/';
  } else if (msg.modelHost) {
    env.remoteHost = msg.modelHost;
  }
  fileBytes.clear();
  const t0 = performance.now();
  const onProgress = (p: any) => {
    if (p?.status === 'progress' && p.file) {
      if (p.total) fileBytes.set(p.file, p.total);
      ctx.postMessage({
        type: 'progress',
        id: msg.id,
        stage: 'download',
        file: p.file,
        loaded: p.loaded,
        total: p.total,
        progress: p.progress,
      });
    }
  };

  const attempt = async (device: 'webgpu' | 'wasm') => {
    activeDevice = device;
    extractor = (await (pipeline as any)('feature-extraction', msg.modelId, {
      device,
      dtype: msg.dtype,
      progress_callback: onProgress,
    })) as FeatureExtractionPipeline;
    const dim = (extractor as any).model?.config?.hidden_size ?? 0;
    // Warm-up run keeps the first real query out of the cold path.
    const warm: any = await (extractor as any)(['warm up'], { pooling: 'cls', normalize: true });
    const warmMs = performance.now() - t0;
    const outputDim = (warm as any).dims?.[1] ?? dim;
    return { warmMs };
  };

  let attempted = msg.device;
  let fallbackReason = '';
  let warmMs = 0;
  try {
    ({ warmMs } = await attempt(attempted));
  } catch (err) {
    if (attempted === 'webgpu') {
      extractor = null;
      fallbackReason = (err as Error)?.message || String(err);
      attempted = 'wasm';
      ({ warmMs } = await attempt('wasm'));
    } else {
      throw err;
    }
  }

  const modelBytes = [...fileBytes.entries()]
    .filter(([file]) => file.endsWith('.onnx') || file.endsWith('.onnx_data'))
    .reduce((sum, [, size]) => sum + size, 0);
  const totalBytes = [...fileBytes.values()].reduce((sum, size) => sum + size, 0);
  const dim = (extractor as any)?.model?.config?.hidden_size || 0;

  post(msg.id, {
    backend: activeDevice,
    requestedBackend: msg.device,
    fallbackReason,
    loadMs: Math.round((performance.now() - t0) * 100) / 100,
    warmMs: Math.round(warmMs * 100) / 100,
    modelBytes,
    totalBytes,
    files: [...fileBytes.keys()],
    dim,
    modelId: msg.modelId,
    dtype: msg.dtype,
  });
}

async function embed(msg: EmbedMessage) {
  if (!extractor) throw new Error('模型尚未加载');
  const { texts, batchSize } = msg;
  const t0 = performance.now();
  const vectors: number[][] = [];
  for (let i = 0; i < texts.length; i += batchSize) {
    const batch = texts.slice(i, i + batchSize);
    const out: any = await extractor(batch, { pooling: 'cls', normalize: true });
    const rows = out.tolist() as number[][];
    for (const row of rows) vectors.push(row);
    ctx.postMessage({
      type: 'progress',
      id: msg.id,
      stage: 'embed',
      done: Math.min(i + batch.length, texts.length),
      total: texts.length,
    });
  }
  const ms = performance.now() - t0;
  const flat = new Float32Array(vectors.length * (vectors[0]?.length || 0));
  vectors.forEach((row, i) => flat.set(row, i * row.length));
  ctx.postMessage(
    {
      type: 'result',
      id: msg.id,
      ok: true,
      payload: {
        count: vectors.length,
        dim: vectors[0]?.length || 0,
        ms: Math.round(ms * 100) / 100,
        vectors: flat.buffer,
        backend: activeDevice,
      },
    },
    [flat.buffer],
  );
}

ctx.onmessage = async (event: MessageEvent<Incoming>) => {
  const msg = event.data;
  try {
    if (msg.type === 'init') await loadModel(msg);
    else if (msg.type === 'embed') await embed(msg);
    else if (msg.type === 'dispose') {
      await (extractor as any)?.dispose?.();
      extractor = null;
      post(msg.id, { disposed: true });
    }
  } catch (err) {
    fail(msg.id, err);
  }
};
