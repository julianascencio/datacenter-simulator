// Optional browser smoke test: PLAYWRIGHT_MODULE can point to an external install.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const report = path.resolve(process.argv[2] || 'outputs/reference-lab.html');
    const screenshots = path.resolve('outputs/browser');
    fs.mkdirSync(screenshots, { recursive: true });
    await page.goto(pathToFileURL(report).href);
    await page.waitForFunction(() => document.querySelectorAll('.js-plotly-plot').length === 7);
    assert.equal(await page.locator('#plot-0 canvas').count() > 0, true);
    // Wait for Plotly's deferred WebGL scene paint before capturing the hall.
    await page.waitForFunction(() => document.getElementById('plot-0')._fullLayout.scene._scene);
    await page.screenshot({ path: path.join(screenshots, 'desktop.png'), fullPage: true });
    for (let i = 0; i < 7; i++) {
      await page.locator('#tab-' + i).click();
      await page.waitForFunction(n => !document.getElementById('panel-' + n).hidden, i);
      await page.waitForFunction(n => {
        const plot = document.getElementById('plot-' + n);
        return Math.abs(plot._fullLayout.width - plot.getBoundingClientRect().width) < 2;
      }, i);
      assert.equal(await page.locator('.panel:visible').count(), 1);
      assert.equal(await page.locator('#tab-' + i).getAttribute('aria-selected'), 'true');
      await page.screenshot({ path: path.join(screenshots, `view-${i}.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('#tab-0').click();
    await page.waitForFunction(() => {
      const plot = document.getElementById('plot-0');
      return plot._fullLayout.width < 390 &&
        Math.abs(plot._fullLayout.width - plot.getBoundingClientRect().width) < 2;
    });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(screenshots, 'mobile.png'), fullPage: true });
    for (const extension of ['.csv', '.json']) {
      assert.equal(fs.existsSync(report.replace(/\.html$/, extension)), true);
    }
    assert.deepEqual(errors, []);
    console.log('7 tabs, WebGL scene, mobile width, exports and JavaScript error checks passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
