#!/usr/bin/env node
/**
 * Download the ONNX weights used by the demo into ./models so the app can run
 * fully offline (and in networks where huggingface.co is unreachable).
 *
 *   node scripts/fetch-models.mjs            # q8 + fp16 + fp32
 *   MODEL_HOST=https://hf-mirror.com node scripts/fetch-models.mjs
 */
import fs from 'node:fs';
import path from 'node:path';

const host = (process.env.MODEL_HOST || 'https://hf-mirror.com').replace(/\/$/, '');
const model = process.env.MODEL_ID || 'Xenova/bge-small-zh-v1.5';
const revision = process.env.MODEL_REVISION || 'main';
const root = path.join(process.cwd(), 'models', model);
const files = [
  'config.json',
  'tokenizer.json',
  'tokenizer_config.json',
  'special_tokens_map.json',
  'vocab.txt',
  'onnx/model.onnx',
  'onnx/model_fp16.onnx',
  'onnx/model_quantized.onnx',
];

async function download(file) {
  const url = `${host}/${model}/resolve/${revision}/${file}`;
  const dest = path.join(root, file);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  for (let attempt = 1; attempt <= 20; attempt++) {
    const start = fs.existsSync(dest) ? fs.statSync(dest).size : 0;
    const res = await fetch(url, { headers: start ? { range: `bytes=${start}-` } : {}, redirect: 'follow' });
    if (res.status === 429) {
      const wait = Number(res.headers.get('retry-after') || 15) * 1000;
      process.stdout.write(`  429, retry in ${wait / 1000}s\n`);
      await new Promise((r) => setTimeout(r, wait));
      continue;
    }
    if (!res.ok) throw new Error(`${res.status} ${url}`);
    const total = start + Number(res.headers.get('content-length') || 0);
    const out = fs.createWriteStream(dest, { flags: start ? 'a' : 'w' });
    let written = start;
    let last = Date.now();
    for await (const chunk of res.body) {
      written += chunk.length;
      if (!out.write(chunk)) await new Promise((r) => out.once('drain', r));
      if (Date.now() - last > 5000) {
        last = Date.now();
        process.stdout.write(`  ${file} ${(written / 1048576).toFixed(1)} / ${(total / 1048576).toFixed(1)} MB\n`);
      }
    }
    await new Promise((r) => out.end(r));
    if (!total || written >= total) {
      console.log(`  ${file} done (${(written / 1048576).toFixed(1)} MB)`);
      return;
    }
  }
  throw new Error(`download failed: ${file}`);
}

console.log(`model: ${model}  host: ${host}`);
for (const file of files) {
  const dest = path.join(root, file);
  if (fs.existsSync(dest) && fs.statSync(dest).size > 1024) {
    console.log(`  skip ${file}`);
    continue;
  }
  process.stdout.write(`-> ${file}\n`);
  await download(file);
}
console.log(`\nDone. Files in ${root}`);
