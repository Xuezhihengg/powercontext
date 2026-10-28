import puppeteer from 'puppeteer-core';
const browser = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: 'new',
  args: ['--enable-unsafe-webgpu', '--enable-features=WebGPU', '--ignore-gpu-blocklist', '--no-sandbox'],
  defaultViewport: { width: 1440, height: 1100 },
});
const page = await browser.newPage();
page.setDefaultTimeout(0);
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto('http://localhost:5173/?autoload=0', { waitUntil: 'networkidle2' });

const init = await page.evaluate(() => window.__KB__.loadModel({ dtype: 'fp16', device: 'auto', quiet: true }).then((r) => r.init));
console.log('backend', init.backend, 'dim', init.dim, 'load', init.loadMs);

const stats = await page.evaluate(() => window.__KB__.ingestSample());
console.log('ingest', JSON.stringify(stats));

await page.type('#query', '浏览器不支持 WebGPU 时怎么降级');
await page.click('#search-btn');
await page.waitForFunction(() => document.querySelectorAll('.hit').length > 0, { timeout: 120000 });
const ui = await page.evaluate(() => ({
  hits: [...document.querySelectorAll('.hit')].map((h) => h.querySelector('.title')?.textContent),
  timings: document.querySelector('#search-timings')?.textContent.trim(),
  badge: document.querySelector('#badge-backend')?.textContent,
}));
console.log('ui', JSON.stringify(ui, null, 1));
await page.screenshot({ path: 'docs/ui.png', fullPage: false });
await browser.close();
