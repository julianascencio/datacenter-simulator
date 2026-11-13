// Check the generated report offline, including scenario switching and mobile layout.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL, fileURLToPath } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const report = path.resolve(process.argv[2] || 'outputs/faraday/faraday-storage.html');
  const screenshots = path.resolve('outputs/faraday-browser');
  fs.mkdirSync(screenshots, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [];
    const remote = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (/^https?:/.test(request.url())) remote.push(request.url());
    });
    await page.goto(pathToFileURL(report).href);
    await page.waitForFunction(() => document.querySelectorAll('.js-plotly-plot').length === 3);
    assert.match(await page.locator('body').innerText(), /Two separate meters/);
    assert.match(await page.locator('body').innerText(), /Reported project metadata/);
    assert.match(await page.locator('body').innerText(), /Lydian Energy/);
    const chart = page.locator('.js-plotly-plot').nth(1);
    assert.equal(await chart.evaluate(el => el.data.filter(trace => trace.visible).length), 7);
    await chart.locator('.updatemenu-header').click();
    await chart.locator('.updatemenu-dropdown-button').filter({ hasText: 'solar_only' }).click();
    assert.equal(await chart.evaluate(el => el.data[7].visible), true);
    assert.equal(await chart.evaluate(el => el.data[14].visible), false);
    const downloads = await page.locator('a[href$=".json"], a[href$=".csv"]')
      .evaluateAll(links => links.map(a => a.href));
    assert.equal(downloads.length, 7);
    for (const href of downloads) {
      assert.ok(fs.existsSync(fileURLToPath(href)), `Missing export: ${href}`);
    }
    await page.screenshot({ path: path.join(screenshots, 'desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth);
    await page.screenshot({ path: path.join(screenshots, 'mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    assert.deepEqual(remote, []);
    console.log('Faraday scenario switching, exports, offline runtime and mobile layout passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
