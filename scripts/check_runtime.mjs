import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const config = JSON.parse(await readFile(new URL('../workflow/runtime.json', import.meta.url), 'utf8'));
const require = createRequire(fileURLToPath(new URL('../workflow/package.json', import.meta.url)));
const { chromium } = require('playwright');
const browser = await chromium.launch({headless: true, executablePath: config.browser});
try {
  const page = await browser.newPage();
  await page.setContent('<main></main>');
  await page.addScriptTag({path: fileURLToPath(new URL('../workflow/node_modules/mermaid/dist/mermaid.min.js', import.meta.url))});
  const ok = await page.evaluate(async () => {
    mermaid.initialize({startOnLoad:false,securityLevel:'strict'});
    const {svg} = await mermaid.render('smoke', 'flowchart LR\n A[中文输入] --> B[文章输出]');
    document.querySelector('main').innerHTML=svg;
    return document.querySelector('svg') !== null;
  });
  if (!ok) throw new Error('Mermaid rendering failed');
  console.log('Browser + Mermaid smoke check passed');
} finally { await browser.close(); }
