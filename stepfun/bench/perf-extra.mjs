import puppeteer from 'puppeteer-core';
import fs from 'node:fs';

const corpus = JSON.parse(fs.readFileSync('public/corpus/corpus.json', 'utf8'));
const texts = corpus.map((d) => d.text);

const browser = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: 'new',
  args: ['--enable-unsafe-webgpu', '--enable-features=WebGPU', '--ignore-gpu-blocklist', '--no-sandbox'],
});
const page = await browser.newPage();
page.setDefaultTimeout(0);
await page.goto('http://localhost:5173/?autoload=0', { waitUntil: 'networkidle2' });
await page.setCacheEnabled(false);

const result = await page.evaluate(async (texts) => {
  const out = { cold: {}, batches: {} };
  for (const cfg of [
    { dtype: 'q8', device: 'wasm' },
    { dtype: 'fp16', device: 'webgpu' },
  ]) {
    const t0 = performance.now();
    const { init, embedder } = await window.__KB__.loadModel({ dtype: cfg.dtype, device: cfg.device, quiet: true });
    out.cold[`${cfg.dtype}-${init.backend}`] = { loadMs: init.loadMs, wallMs: performance.now() - t0, modelBytes: init.modelBytes };
    for (const batch of [1, 8, 16, 32]) {
      const runs = [];
      for (let i = 0; i < 3; i++) {
        const r = await embedder.embed(texts, batch);
        runs.push(r.ms);
      }
      runs.sort((a, b) => a - b);
      out.batches[`${cfg.dtype}-${init.backend}-b${batch}`] = {
        medianMs: Math.round(runs[1] * 100) / 100,
        charsPerSec: Math.round(texts.join('').length / (runs[1] / 1000)),
      };
    }
  }
  return out;
}, texts);

console.log(JSON.stringify(result, null, 2));
fs.writeFileSync('bench/results/extra.json', JSON.stringify({ timestamp: new Date().toISOString(), ...result }, null, 2));
await browser.close();
