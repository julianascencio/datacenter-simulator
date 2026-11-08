// Validate the exported report's plots, audit files and narrow-screen layout.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL, fileURLToPath } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const report = path.resolve(process.argv[2] || 'outputs/infrastructure/infrastructure-study.html');
  const output = path.resolve('outputs/infrastructure-browser');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    const requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (/^https?:/.test(request.url())) requests.push(request.url());
    });
    for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.goto(pathToFileURL(report).href);
      await page.waitForFunction(() => Array.from(document.querySelectorAll('.js-plotly-plot'))
        .filter(plot => plot._fullLayout && plot._fullData).length === 4);
      assert.equal(await page.locator('h1').textContent(),
        'From equipment content to a 20 MW IT design');
      assert.equal(await page.locator('.card').count(), 4);
      assert.match(await page.locator('.notice').textContent(), /not a quotation/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      const downloads = await page.locator('a[download]').evaluateAll(links => links.map(a => a.href));
      assert.equal(downloads.length, 10);
      for (const url of downloads) assert.ok(fs.existsSync(fileURLToPath(url)), url);
      const data = await page.evaluate(() => document.getElementById('infrastructure-chart-0').data[0]);
      assert.equal(data.x.length, 13);
      assert.equal(data.measure[12], 'total');
      assert.ok(Math.abs(data.y.slice(0, 12).reduce((a, b) => a + b, 0) - 854) < 1e-8);
      await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, [], 'Offline report must not fetch remote scripts or assets');
    console.log('Infrastructure plots, cost data, ten audit downloads and desktop/mobile layout passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
