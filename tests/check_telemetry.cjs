// Check the standalone telemetry report without network access, on desktop and mobile.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL, fileURLToPath } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const report = path.resolve(process.argv[2] || 'outputs/telemetry/telemetry.html');
  const screenshots = path.resolve('outputs/telemetry-browser');
  fs.mkdirSync(screenshots, { recursive: true });
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('https://**/*', route => route.abort());
    await page.route('http://**/*', route => route.abort());
    await page.goto(pathToFileURL(report).href);
    assert.equal(await page.locator('h1').innerText(), 'Unified facility telemetry');
    assert.equal(await page.locator('.plotly-graph-div').count(), 4);
    assert.equal(await page.locator('.main-svg').count() >= 4, true);
    assert.match(await page.locator('body').innerText(), /four pages only/);
    // Plotly also inserts toolbar anchors; validate the report's sixteen data downloads.
    const downloads = page.locator('a[href$=".csv"], a[href$=".json"], a[href$=".jsonl"], a[href$=".lp"]');
    assert.equal(await downloads.count(), 16);
    for (const href of await downloads.evaluateAll(links => links.map(a => a.href))) {
      assert.ok(fs.existsSync(fileURLToPath(href)), `Missing local download: ${href}`);
    }
    // Plotly legend interaction must change trace visibility.
    await page.locator('.legendtoggle').first().click();
    await page.waitForFunction(() => document.querySelector('.plotly-graph-div').data[0].visible === 'legendonly');
    await page.screenshot({ path: path.join(screenshots, 'telemetry-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth);
    await page.screenshot({ path: path.join(screenshots, 'telemetry-mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log('Telemetry report: offline plots, legend interaction, downloads and mobile layout passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
