import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const runtime = JSON.parse(await readFile(join(here, 'runtime.json'), 'utf8'));
const require = createRequire(join(runtime.node_packages, '../package.json'));
const { chromium } = require('playwright');
const run = process.argv[2];
const browser = await chromium.launch({ headless: true, executablePath: runtime.browser });
const checks = [];
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  // Inspect ClipboardItem payload without altering the user's system clipboard.
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { value: { write: async items => {
      const result = {};
      for (const type of items[0].types) result[type] = await (await items[0].getType(type)).text();
      window.copiedPayload = result;
    } }, configurable: true });
  });
  await mkdir(join(run, '.qa'), { recursive: true });
  for (const width of [320, 375, 430, 1040]) {
    await page.setViewportSize({ width, height: 960 });
    await page.goto(pathToFileURL(join(run, 'preview.html')).href);
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() => Array.from(document.images).every(i => i.complete && i.naturalWidth > 0));
    const layout = await page.evaluate(() => ({
      width: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      articleWidth: document.getElementById('article').clientWidth,
      title: document.querySelector('.article-header h2').textContent,
      images: [...document.images].map(i => ({ width: i.naturalWidth, height: i.naturalHeight })),
      missingImages: [...document.images].filter(i => i.naturalWidth === 0).length,
      rawMermaidCode: document.getElementById('article').innerText.includes('flowchart TD'),
    }));
    if (layout.documentWidth > width || layout.missingImages || layout.rawMermaidCode) throw new Error(JSON.stringify(layout));
    checks.push(layout);
    if (width === 375 || width === 1040) await page.screenshot({ path: join(run, '.qa', `preview-${width}.png`), fullPage: true });
  }
  await page.click('#copy-body');
  await page.waitForFunction(() => document.getElementById('message').textContent.startsWith('已复制'));
  const copied = await page.evaluate(() => ({
    richHtml: Boolean(window.copiedPayload?.['text/html']),
    plainText: Boolean(window.copiedPayload?.['text/plain']),
    containsArticle: window.copiedPayload?.['text/plain'].trim() === document.getElementById('article').innerText.trim(),
    containsControls: window.copiedPayload?.['text/html'].includes('copy-body'),
    containsImage: window.copiedPayload?.['text/html'].includes('data:image/png;base64,'),
  }));
  if (!copied.richHtml || !copied.plainText || !copied.containsArticle || copied.containsControls) throw new Error(JSON.stringify(copied));
  await page.click('#copy-title');
  await page.waitForFunction(() => window.copiedPayload?.['text/plain'] === document.querySelector('.controls h1').textContent);
  const titleMatches = await page.evaluate(() => window.copiedPayload?.['text/plain'] === document.querySelector('.controls h1').textContent);
  await page.click('#copy-digest');
  await page.waitForFunction(() => window.copiedPayload?.['text/plain'] === document.getElementById('digest').textContent);
  const digestMatches = await page.evaluate(() => window.copiedPayload?.['text/plain'] === document.getElementById('digest').textContent);
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.screenshot({ path: join(run, '.qa/preview-dark.png') });
  if (errors.length || !titleMatches || !digestMatches) throw new Error(JSON.stringify({ errors, titleMatches, digestMatches }));
  const report = { checkedAt: new Date().toISOString(), checks,
    clipboardPayload: copied, titleMatches, digestMatches, pageErrors: errors,
    limitation: 'Local Chromium layout and ClipboardItem payload only; no WeChat paste, console or device verification.' };
  await writeFile(join(run, '.qa/layout-checks.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ widths: checks.map(c => c.width), overflow: false, missingImages: 0,
    clipboardPayload: copied, titleMatches, digestMatches, pageErrors: errors }));
} finally {
  await browser.close();
}
