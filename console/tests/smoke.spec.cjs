// Smoke test: node console/tests/smoke.spec.cjs (needs a running API with demo data: python -m app.demo)
const { chromium } = require('playwright');
const BASE = process.env.GP_URL || 'http://localhost:8000';
(async () => {
  const b = await chromium.launch(); const errs = [];
  const ctx = await b.newContext({ viewport: { width: 1300, height: 800 }, permissions: ['geolocation'], geolocation: { latitude: -12.5, longitude: -55.7, accuracy: 5 } });
  const p = await ctx.newPage(); p.on('pageerror', e => errs.push(e.message));
  await p.goto(BASE + '/console/'); await p.click('#login');
  await p.waitForSelector('#legend .pill'); const legend = await p.textContent('#legend');
  if (!/cleared_after_2020 \d+/.test(legend) || !/compliant/.test(legend)) throw new Error('legend: ' + legend);
  await p.click('#tour'); await p.waitForSelector('#selx img', { timeout: 15000 });   // cleared plot shows before/after
  const sel = await p.textContent('#sel'); if (!/cleared_after_2020/.test(sel) || !/Alert #/.test(sel)) throw new Error('tour: ' + sel);
  await p.screenshot({ path: process.env.SHOT || '/tmp/claude-0/run/console.png' });
  // field app
  const f = await ctx.newPage(); f.on('pageerror', e => errs.push(e.message)); await f.goto(BASE + '/field/'); await f.click('#go');
  await f.waitForSelector('#app:not([hidden])'); const txt = await f.textContent('#plots'); console.log('field plots view:', txt.trim().slice(0, 60));
  if (errs.length) throw new Error('page errors: ' + errs.join('; '));
  console.log('SMOKE OK'); await b.close();
})().catch(e => { console.error('FAIL', e.message); process.exit(1) });
