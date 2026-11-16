/* Offline report smoke test at desktop/mobile sizes. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const target = path.resolve(process.argv[2] || 'outputs/power-quality/power-quality.html');
  const output = 'outputs/power-quality-browser';
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH });
  try {
    for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
      const page = await browser.newPage({ viewport: { width, height } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto('file://' + target);
      await page.waitForFunction(() => document.querySelector('.js-plotly-plot')?.data?.length === 9);
      assert.match(await page.textContent('body'), /not Pst/);
      assert.match(await page.textContent('body'), /Sustained-load stress test/);
      assert.equal(await page.locator('table').count(), 2);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2);
      assert.equal(overflow, false, `${name}: page overflows viewport`);
      await page.locator('.legendtoggle').first().click();
      await page.waitForFunction(() => document.querySelector('.js-plotly-plot').data[0].visible === 'legendonly');
      await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
      assert.deepEqual(errors, []);
      await page.close();
      console.log(`${name}: charts, tables, legend interaction and viewport passed`);
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
