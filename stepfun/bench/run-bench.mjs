#!/usr/bin/env node
/**
 * Drive the running app in Chrome and run the in-browser benchmark.
 *
 * Usage:
 *   npm run dev            # terminal 1
 *   npm run bench -- q8 auto fp16 webgpu fp32 wasm
 */
import fs from 'node:fs';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const appUrl = process.env.APP_URL || 'http://127.0.0.1:5173/?autoload=0';
const chrome = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const args = process.argv.slice(2);
const configs = [];
for (let i = 0; i < args.length; i += 2) {
  configs.push({ dtype: args[i], device: args[i + 1] || 'auto' });
}
if (!configs.length) configs.push({ dtype: 'q8', device: 'auto' });

const headless = process.env.HEADLESS !== '0';
const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: headless ? 'new' : false,
  args: ['--enable-unsafe-webgpu', '--enable-features=WebGPU', '--ignore-gpu-blocklist', '--no-sandbox'],
  defaultViewport: { width: 1440, height: 1000 },
});

const page = await browser.newPage();
page.setDefaultTimeout(0);
page.on('console', (msg) => {
  const text = msg.text();
  if (!text.includes('[vite]')) console.log('[page]', text);
});
page.on('pageerror', (err) => console.error('[pageerror]', err.message));

await page.goto(appUrl, { waitUntil: 'networkidle2', timeout: 120000 });
await page.waitForFunction('window.__KB__ && window.__KB__.api', { timeout: 60000 });

const outDir = path.join(process.cwd(), 'bench', 'results');
fs.mkdirSync(outDir, { recursive: true });

const reports = [];
for (const cfg of configs) {
  console.log(`\n=== ${cfg.dtype} / ${cfg.device} ===`);
  const started = Date.now();
  const report = await page.evaluate(
    (c) => window.__KB__.bench(c.dtype, c.device),
    cfg,
  );
  if (!report) throw new Error(`bench failed for ${cfg.dtype}/${cfg.device}`);
  report.wallClockMs = Date.now() - started;
  reports.push(report);
  console.log(
    `${report.backend}/${report.dtype} model=${(report.modelBytes / 1048576).toFixed(1)}MB ` +
      `docEmbed=${report.timings.docEmbedMs}ms search=${report.timings.searchMedianMs}ms ` +
      `e2e=${report.timings.e2eMedianMs}ms recall@5=${report.quality.recallAt5} ndcg@5=${report.quality.ndcgAt5}`,
  );
  fs.writeFileSync(path.join(outDir, `${report.dtype}-${report.backend}.json`), JSON.stringify(report, null, 2));
}

fs.writeFileSync(path.join(outDir, `summary-${Date.now()}.json`), JSON.stringify(reports, null, 2));
console.log(`\nSaved ${reports.length} report(s) to ${outDir}`);
await browser.close();
