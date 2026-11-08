// Verify the packaged offline report and its audit data on desktop and mobile.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL, fileURLToPath } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const file = path.resolve(process.argv[2] || 'outputs/wyoming/wyoming-grid-management.html');
  const browser = await chromium.launch({ headless: true });
  const output = path.resolve('outputs/engineering-browser');
  fs.mkdirSync(output, { recursive: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(file).href);
    await page.locator('.js-plotly-plot .main-svg').first().waitFor();
    assert.equal(await page.locator('.js-plotly-plot').count(), 2);
    assert.match(await page.locator('main').innerText(), /operational success is not established/);
    for (const link of await page.locator('a').all()) {
      const target = await link.evaluate(a => a.href);
      assert.ok(fs.existsSync(fileURLToPath(target)), target);
    }
    await page.screenshot({ path: path.join(output, 'wyoming-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(400);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(output, 'wyoming-mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log('Wyoming report charts, audit links, JavaScript and mobile layout passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
