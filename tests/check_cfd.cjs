// Verify field/time/slice controls against exported solver arrays, including mobile and offline use.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL, fileURLToPath } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const report = path.resolve(process.argv[2] || 'outputs/cfd/cfd-3d.html');
  const output = path.resolve('outputs/cfd-browser');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (/^https?:/.test(request.url())) requests.push(request.url()); });
    for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.goto(pathToFileURL(report).href);
      await page.waitForFunction(() => document.body.dataset.scenario === 'Normal airflow');
      assert.equal(await page.locator('.js-plotly-plot').count(), 4);
      const normalPeak = parseFloat(await page.locator('#peak').textContent());
      assert.ok(normalPeak > 20);
      const arrays = await page.evaluate(() => {
        const p=JSON.parse(document.getElementById('cfd-data').textContent);
        const c=p.cases['Normal airflow'], f=c.frames.at(-1);
        const k=Number(document.getElementById('height').value);
        return {expected:f.temperature[k], actual:document.getElementById('plan').data[0].z[0][0],
          volume:document.getElementById('volume').data[0].value.length, cells:c.summary.cells};
      });
      assert.equal(arrays.actual, arrays.expected);
      assert.equal(arrays.volume, arrays.cells);
      await page.locator('#height').evaluate(el => { el.value='0'; el.dispatchEvent(new Event('input')); });
      await page.waitForFunction(() => document.body.dataset.height === '0');
      await page.selectOption('#field', 'pressure');
      await page.waitForFunction(() => document.body.dataset.field === 'pressure');
      assert.match(await page.locator('#conditions').textContent(), /Gauge pressure/);
      await page.selectOption('#field', 'temperature');
      await page.waitForFunction(() => document.body.dataset.field === 'temperature');
      await page.selectOption('#scenario', 'Half airflow');
      await page.waitForFunction(() => document.body.dataset.scenario === 'Half airflow');
      assert.ok(parseFloat(await page.locator('#peak').textContent()) > normalPeak);
      assert.equal(await page.locator('#rack-table tr').count(), 4);
      await page.locator('#time').evaluate(el => { el.value='0'; el.dispatchEvent(new Event('input')); });
      await page.waitForFunction(() => document.body.dataset.frame === '0');
      assert.equal(parseFloat(await page.locator('#peak').textContent()), 20);
      await page.getByRole('button', { name:'Play', exact:true }).click();
      await page.waitForFunction(() => Number(document.body.dataset.frame) > 0);
      await page.getByRole('button', { name:'Pause', exact:true }).click();
      await page.locator('#time').evaluate(el => { el.value=el.max; el.dispatchEvent(new Event('input')); });
      await page.waitForFunction(() => document.body.dataset.frame === document.getElementById('time').max);
      const downloads = await page.locator('a[download]').evaluateAll(links => links.map(a => a.href));
      assert.equal(downloads.length, 17);
      for (const url of downloads) assert.ok(fs.existsSync(fileURLToPath(url)), url);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.screenshot({ path:path.join(output, `${name}.png`), fullPage:true });
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, [], 'CFD report must run offline');
    console.log('CFD 3D fields, scenario/time/slice controls, array bindings and desktop/mobile checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
