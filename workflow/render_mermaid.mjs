import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const runtime = JSON.parse(await readFile(join(here, 'runtime.json'), 'utf8'));
const require = createRequire(join(runtime.node_packages, '../package.json'));
const { chromium } = require('playwright');
const specs = JSON.parse(await readFile(process.argv[2], 'utf8'));
const browser = await chromium.launch({ headless: true, executablePath: runtime.browser });
try {
  const page = await browser.newPage({ viewport: { width: 1400, height: 1400 }, deviceScaleFactor: 2 });
  await page.setContent('<html lang="zh-CN"><meta charset="utf-8"><body style="margin:0;background:white"><main></main></body></html>');
  await page.addScriptTag({ path: join(here, 'node_modules/mermaid/dist/mermaid.min.js') });
  await page.evaluate(() => mermaid.initialize({
    startOnLoad: false, securityLevel: 'strict', theme: 'base',
    themeVariables: { fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif', fontSize: '19px',
      primaryColor: '#f1f5f3', primaryTextColor: '#172e24', primaryBorderColor: '#90aa9b',
      lineColor: '#486554', secondaryColor: '#0fdc78', tertiaryColor: '#ffffff' },
    flowchart: { htmlLabels: false, useMaxWidth: false, padding: 20, wrappingWidth: 280, rankSpacing: 28 },
  }));
  for (const [index, spec] of specs.entries()) {
    const svg = await page.evaluate(async ({ code, index }) => {
      const { svg } = await mermaid.render(`article-diagram-${index}`, code);
      document.querySelector('main').innerHTML = svg;
      const el = document.querySelector('main svg');
      const box = el.viewBox.baseVal;
      el.style.width = `${Math.ceil(box.width)}px`;
      el.style.height = `${Math.ceil(box.height)}px`;
      el.style.maxWidth = 'none';
      return svg;
    }, { code: spec.code, index });
    await mkdir(dirname(spec.output), { recursive: true });
    await writeFile(spec.output.replace(/\.png$/, '.svg'), svg);
    await page.locator('main svg').screenshot({ path: spec.output });
  }
} finally {
  await browser.close();
}
