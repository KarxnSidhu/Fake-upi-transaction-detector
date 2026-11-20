/* Optional local runner: npm install && npx playwright install chromium */
const {chromium} = require('playwright');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const checks = require('./checks.cjs');
const fixtures = require('./fixtures.cjs');
const root = path.resolve(__dirname, '../..');
const routes = {
  '/': ['static/index.html', 'text/html'],
  '/static/style.css': ['static/style.css', 'text/css'],
  '/static/script.js': ['static/script.js', 'text/javascript']
};

(async () => {
  const server = http.createServer(async (req, res) => {
    const route = routes[req.url];
    if (!route) { res.writeHead(404); res.end(); return; }
    try { const content = await fs.readFile(path.join(root, route[0])); res.writeHead(200, {'Content-Type':route[1]}); res.end(content); }
    catch { res.writeHead(500); res.end(); }
  });
  let browser;
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    browser = await chromium.launch();
    const evidence = path.join(root, 'frontend-evidence', 'local-run');
    await fs.mkdir(evidence, {recursive:true});
    const reports = [];
    for (const [width, height] of [[390,844], [768,1024], [1440,900]]) {
      const page = await browser.newPage({viewport:{width,height}, reducedMotion:'reduce'});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.addInitScript(fixtures);
      await page.goto(`http://127.0.0.1:${server.address().port}`);
      const report = await page.evaluate(checks);
      if (errors.length) throw new Error(errors.join('\n'));
      await page.evaluate(() => {document.getElementById('toast').hidden=true;});
      await page.screenshot({path:path.join(evidence, `${width}x${height}.png`),fullPage:true});
      reports.push(report);
      console.log(`${width}x${height}: ${report.results.length} checks passed`);
      await page.close();
    }
    await fs.writeFile(path.join(evidence, 'assertions.json'),JSON.stringify(reports,null,2));
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {console.error(error); process.exitCode=1;});
