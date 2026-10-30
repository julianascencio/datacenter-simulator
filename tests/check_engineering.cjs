// Verify equipment identity, cross-view selection and failure replay in a real browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const input = path.resolve(process.argv[2] || 'outputs/engineering/engineering-lab.html');
  const output = path.resolve('outputs/engineering-browser');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(input).href);
    await page.waitForFunction(() => window.labReady, { timeout: 60000 });
    assert.equal(await page.locator('.plot .svg-container').count(), 5);
    await page.selectOption('#equipment', 'rack-01');
    await page.waitForFunction(() => window.labState.selected === 'rack-01');
    assert.deepEqual((await page.evaluate(() => window.labState.related)).sort(),
      ['rack-01', 'feed-A', 'feed-B', 'cdu', 'switch'].sort());
    for (const domain of ['scene', 'plan', 'electrical', 'cooling', 'communications']) {
      assert.ok(await page.evaluate(id => document.getElementById(id).data.some(trace =>
        trace.meta?.equipment_ids.includes('rack-01') && trace.opacity === 1), domain));
    }
    await page.evaluate(() => {
      const frames = JSON.parse(document.getElementById('lab-data').textContent).frames;
      const slider = document.getElementById('time');
      slider.value = String(frames.findIndex(frame => frame.time_s >= 62 && frame.time_s < 180));
      slider.dispatchEvent(new Event('input'));
    });
    await page.waitForFunction(() => window.labState.time_s >= 62);
    assert.match(await page.locator('#details').innerText(), /Active feed: feed-B/);
    assert.match(await page.locator('#time-label').innerText(), /Failed: feed-A/);
    await page.screenshot({ path: path.join(output, 'engineering-desktop.png'), fullPage: true });
    // Trigger Plotly's click callback with a point carrying the actual equipment ID.
    await page.evaluate(() => document.getElementById('cooling').emit('plotly_click', {
      points: [{ customdata: 'rack-02' }]
    }));
    await page.waitForFunction(() => window.labState.selected === 'rack-02');
    assert.equal(await page.locator('#equipment').inputValue(), 'rack-02');
    await page.click('#play');
    const previous = await page.evaluate(() => window.labState.time_s);
    await page.waitForFunction(time => window.labState.time_s !== time, previous);
    await page.click('#play');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(500);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(output, 'engineering-mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log('Linked equipment, five views, A/B replay, playback and mobile layout passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
