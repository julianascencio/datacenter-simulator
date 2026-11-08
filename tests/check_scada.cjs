// Exercise the exported catalogue and its actual downloadable artifacts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL, fileURLToPath } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const file = path.resolve(process.argv[2] || 'outputs/scada/scada-model.html');
  const screenshots = path.resolve('outputs/scada-browser');
  fs.mkdirSync(screenshots, {recursive: true});
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [], remoteRequests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (/^https?:/.test(request.url())) remoteRequests.push(request.url());
    });
    await page.goto(pathToFileURL(file).href);
    assert.equal(await page.locator('.profile').count(), 50);
    assert.equal(await page.locator('#count').innerText(), '50 devices shown');
    const downloads = await page.locator('a[download]').evaluateAll(links => links.map(a => a.href));
    assert.ok(downloads.length >= 63);
    for (const url of downloads) {
      const local = fileURLToPath(url);
      assert.ok(fs.existsSync(local), local);
      if (local.endsWith('.json')) JSON.parse(fs.readFileSync(local, 'utf8'));
    }
    await page.locator('#search').fill('battery_voltage_v');
    const visible = page.locator('.profile:not(.hidden)');
    assert.ok(await visible.count() > 0);
    assert.ok(await visible.count() < 50);
    const ups = visible.filter({has: page.locator('summary', {hasText: 'Uninterruptible power supply'})});
    await ups.locator('summary').click();
    assert.ok(await ups.locator('table').count() === 2);
    assert.match(await ups.innerText(), /output_line_power_kw/);
    await page.screenshot({path: path.join(screenshots, 'ups-desktop.png'), fullPage: true});
    await page.locator('#search').fill('');
    await page.locator('#domain').selectOption('Cooling');
    assert.equal(await visible.count(), 14);
    await page.setViewportSize({width: 390, height: 844});
    await visible.first().locator('summary').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({path: path.join(screenshots, 'cooling-mobile.png'), fullPage: true});
    await page.locator('#search').fill('no-such-device-or-point');
    assert.equal(await visible.count(), 0);
    assert.equal(await page.locator('#count').innerText(), '0 devices shown');
    assert.deepEqual(errors, []);
    assert.deepEqual(remoteRequests, []);
    console.log('SCADA catalogue: 50 profiles, field/domain filters, schemas/downloads and mobile layout passed.');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
