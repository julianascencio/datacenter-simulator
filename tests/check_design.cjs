// Exercise scenario changes, numerical bindings, all downloads and offline mobile rendering.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL, fileURLToPath } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const report = path.resolve(process.argv[2] || 'outputs/design/design-workbench.html');
  const output = path.resolve('outputs/design-browser');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (/^https?:/.test(request.url())) requests.push(request.url());
    });
    for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.goto(pathToFileURL(report).href);
      await page.waitForFunction(() => document.body.dataset.scenario);
      assert.equal(await page.locator('.js-plotly-plot').count(), 6);
      assert.equal(await page.locator('#scenario option').count(), 15);
      assert.equal(await page.locator('#equipment tr').count(), 4);
      const snapshot = await page.evaluate(() => {
        const values = JSON.parse(document.getElementById('design-data').textContent);
        return values.scenarios[document.body.dataset.scenario];
      });
      const flow = await page.evaluate(() => document.getElementById('chart-0').data[0].link.value);
      assert.ok(Math.abs(flow.reduce((a, b) => a + b, 0) - snapshot.summary.design_facility_kw) < 1e-8);
      const energyPue = await page.locator('#pue').textContent();
      await page.selectOption('#scenario', 'dx / N');
      await page.waitForFunction(() => document.body.dataset.scenario === 'dx / N');
      assert.match(await page.locator('#status').textContent(), /Contingency capacity fails/);
      assert.notEqual(await page.locator('#pue').textContent(), energyPue);
      await page.selectOption('#scenario', 'direct_to_chip / 2N');
      await page.waitForFunction(() => document.body.dataset.scenario === 'direct_to_chip / 2N');
      assert.match(await page.locator('#banks').textContent(), /2 bank\(s\)/);
      assert.equal(await page.locator('#equipment .fail').count(), 0);
      const downloads = await page.locator('a[download]').evaluateAll(links => links.map(a => a.href));
      assert.equal(downloads.length, 11);
      for (const url of downloads) assert.ok(fs.existsSync(fileURLToPath(url)), url);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, [], 'The report must work with no external requests');
    console.log('Design scenario changes, power balance, exports and desktop/mobile layout passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
