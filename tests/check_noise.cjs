// Verify the viewer against Python-exported arrays, including mobile/offline use.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL, fileURLToPath} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async()=>{
 const report=path.resolve(process.argv[2]||'outputs/noise/noise-3d.html');
 const output=path.resolve('outputs/noise-browser');fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage();const errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});
  for(const [name,width,height] of [['desktop',1440,1000],['mobile',390,844]]){
   await page.setViewportSize({width,height});await page.goto(pathToFileURL(report).href);
   await page.waitForFunction(()=>document.body.dataset.scenario==='Baseline');
   assert.equal(await page.locator('.js-plotly-plot').count(),5);
   const baseline=parseFloat(await page.locator('#receiver-level').textContent());
   assert.ok(baseline>0);
   const arrays=await page.evaluate(()=>{
    const c=JSON.parse(document.getElementById('noise-data').textContent).cases.Baseline;
    const k=Number(document.getElementById('height').value);
    return {expected:c.fields.A[k],actual:document.getElementById('plan').data[0].z[0][0],
      excluded:c.fields.A.filter(v=>v===null).length,summary:c.summary.excluded_cells};
   });
   assert.equal(arrays.expected,arrays.actual);assert.equal(arrays.excluded,arrays.summary);assert.ok(arrays.excluded>0);
   await page.selectOption('#field','1000');await page.waitForFunction(()=>document.body.dataset.field==='1000');
   assert.match(await page.locator('#conditions').textContent(),/1000 Hz/);
   await page.locator('#height').evaluate(el=>{el.value='0';el.dispatchEvent(new Event('input'));});
   await page.waitForFunction(()=>document.body.dataset.height==='0');
   await page.selectOption('#field','A');await page.waitForFunction(()=>document.body.dataset.field==='A');
   await page.selectOption('#scenario','Source treatment');await page.waitForFunction(()=>document.body.dataset.scenario==='Source treatment');
   assert.ok(parseFloat(await page.locator('#receiver-level').textContent())<baseline-3);
   await page.selectOption('#receiver','Room entrance');await page.waitForFunction(()=>document.body.dataset.receiver==='Room entrance');
   assert.equal(await page.locator('#receivers tr').count(),3);assert.equal(await page.locator('#room tr').count(),8);
   const downloads=await page.locator('a[download]').evaluateAll(a=>a.map(x=>x.href));assert.equal(downloads.length,25);
   for(const url of downloads)assert.ok(fs.existsSync(fileURLToPath(url)));
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await page.screenshot({path:path.join(output,`${name}.png`),fullPage:true});
  }
  assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
  console.log('Acoustic 3D fields, exclusions, scenario/receiver/band/slice controls and offline mobile checks passed.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
