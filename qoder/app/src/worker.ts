import { pipeline, env } from '@huggingface/transformers';

env.allowLocalModels = true;
env.localModelPath = '/models/';
env.allowRemoteModels = false;

const MODEL_ID = 'Xenova/bge-small-zh-v1.5';

let embedder: any = null;
let backend = 'wasm';
let modelSizeBytes = 0;

function detectDtypeFile(dtype: string): string {
  if (dtype === 'fp16') return 'model_fp16.onnx';
  if (dtype === 'q8') return 'model_quantized.onnx';
  return 'model.onnx';
}

async function probeLocalModelSize(dtype: string): Promise<number> {
  const file = detectDtypeFile(dtype);
  const url = `/models/${MODEL_ID}/onnx/${file}`;
  try {
    const res = await fetch(url, { method: 'HEAD' });
    if (!res.ok) return 0;
    const cl = res.headers.get('content-length');
    return cl ? parseInt(cl, 10) : 0;
  } catch {
    return 0;
  }
}

async function tryLoad(dtype: string, device: string): Promise<any> {
  return await pipeline(
    'feature-extraction',
    MODEL_ID,
    { dtype, device } as any,
  );
}

async function getModel() {
  if (embedder) return embedder;

  const hasWebGPU = typeof navigator !== 'undefined' && !!(navigator as any).gpu;
  const dtypeCandidates = ['q8', 'fp16'];
  const deviceOrder = hasWebGPU ? ['webgpu', 'wasm'] : ['wasm'];

  let lastErr: unknown = null;

  for (const dtype of dtypeCandidates) {
    modelSizeBytes = await probeLocalModelSize(dtype);
    for (const device of deviceOrder) {
      try {
        embedder = await tryLoad(dtype, device);
        backend = device;
        return embedder;
      } catch (e) {
        lastErr = e;
      }
    }
  }

  env.allowRemoteModels = true;
  for (const dtype of dtypeCandidates) {
    for (const device of deviceOrder) {
      try {
        embedder = await tryLoad(dtype, device);
        backend = device;
        return embedder;
      } catch (e) {
        lastErr = e;
      }
    }
  }

  throw lastErr instanceof Error ? lastErr : new Error(String(lastErr));
}

self.onmessage = async (e: MessageEvent) => {
  const { id, type, texts } = e.data;
  const post = (msg: Record<string, unknown>) =>
    (self as unknown as Worker).postMessage({ id, ...msg });

  try {
    if (type === 'embed') {
      const model = await getModel();
      const results: number[][] = [];
      for (const text of texts) {
        const output = await model(text, { pooling: 'cls' } as any);
        const arr = output?.data ?? output?.tolist?.() ?? Array.from(output);
        results.push(Array.isArray(arr) ? arr : Array.from(arr as Iterable<number>));
      }
      post({ results });
    } else if (type === 'ready') {
      const t0 = performance.now();
      await getModel();
      const loadTimeMs = Math.round(performance.now() - t0);
      post({
        ready: true,
        backend,
        modelSizeBytes,
        loadTimeMs,
        dtype: backend === 'webgpu' ? 'q8' : 'q8',
      });
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    post({ error: message });
  }
};
