// Exercise the generated documentation as a reader, including all six tutorials.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL, fileURLToPath } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const root = path.resolve(process.argv[2] || 'docs/_build/html');
  const screenshots = path.resolve('outputs/docs-browser');
  fs.mkdirSync(screenshots, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(path.join(root, 'index.html')).href);
    const sections = ['User Guide', 'Example Gallery', 'API Reference', 'Research', 'Contributing'];
    for (const title of sections) {
      assert.ok(await page.getByRole('link', { name: title, exact: true }).count(), title);
    }
    assert.ok(await page.locator('img[alt="ASVA Consulting"]').evaluate(img => img.naturalWidth > 0));
    await page.screenshot({ path: path.join(screenshots, 'home-desktop.png'), fullPage: true });
    await page.locator('a[href="gallery/index.html"]').first().click();
    const cards = page.locator('.sphx-glr-thumbcontainer');
    assert.equal(await cards.count(), 6, 'The gallery should contain six executable tutorials');
    await page.screenshot({ path: path.join(screenshots, 'gallery-desktop.png'), fullPage: true });
    const examples = await cards.locator('a.reference.internal').evaluateAll(links =>
      [...new Set(links.map(link => link.href.split('#')[0]))]);
    assert.equal(examples.length, 6);
    for (const url of examples) {
      await page.goto(url);
      const text = await page.locator('article').innerText();
      assert.match(text, /Level:.*(Beginner|Intermediate|Advanced)/);
      assert.match(text, /Step 1/);
      const figures = page.locator('img[src*="sphx_glr_"]:not([src*="thumb"])');
      assert.ok(await figures.count() >= 2, `Expected multiple plotted results: ${url}`);
      for (const image of await figures.all()) {
        assert.ok(await image.evaluate(img => img.complete && img.naturalWidth > 0));
      }
      const downloads = await page.locator('a.download').evaluateAll(links => links.map(a => a.href));
      for (const extension of ['.py', '.ipynb']) {
        const download = downloads.find(link => link.endsWith(extension));
        assert.ok(download, `Missing ${extension} download: ${url}`);
        assert.ok(fs.existsSync(fileURLToPath(download)));
      }
    }
    await page.setViewportSize({ width: 390, height: 844 });
    for (const [name, relative] of [
      ['home', 'index.html'], ['gallery', 'gallery/index.html'],
      ['tutorial', 'gallery/methods/plot_device_models.html'],
    ]) {
      await page.goto(pathToFileURL(path.join(root, relative)).href);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false,
                   `Mobile page overflow: ${relative}`);
      await page.screenshot({ path: path.join(screenshots, `${name}-mobile.png`), fullPage: true });
    }
    assert.deepEqual(errors, []);
    console.log('Documentation navigation, six tutorials, figures, downloads and mobile layout passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
