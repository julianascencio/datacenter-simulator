// Verify the offline report, downloads and actual Plotly interaction on two viewports.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL, fileURLToPath } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const report = path.resolve(process.argv[2] || 'outputs/speed-to-power/speed-to-power.html');
  const screenshots = path.resolve('outputs/speed-to-power-browser');
  fs.mkdirSync(screenshots, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [], remote = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (/^https?:/.test(request.url())) remote.push(request.url());
    });
    await page.goto(pathToFileURL(report).href);
    await page.waitForFunction(() => document.querySelectorAll('.js-plotly-plot').length === 3);
    assert.match(await page.locator('body').innerText(), /4,317 locations/);
    assert.match(await page.locator('body').innerText(), /Native synthetic engineering scenario/);
    const chart = page.locator('.js-plotly-plot').first();
    await chart.locator('.legendtoggle').first().click();
    await page.waitForFunction(() =>
      document.querySelector('.js-plotly-plot').data[0].visible === 'legendonly');
    const downloads = await page.locator('a[href$=".json"], a[href$=".csv"]')
      .evaluateAll(links => links.map(a => a.href));
    assert.equal(downloads.length, 10);
    for (const href of downloads) assert.ok(fs.existsSync(fileURLToPath(href)));
    await page.screenshot({ path: path.join(screenshots, 'desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth);
    await page.screenshot({ path: path.join(screenshots, 'mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    assert.deepEqual(remote, []);
    console.log('Speed-to-power interaction, downloads, offline runtime and mobile checks passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
