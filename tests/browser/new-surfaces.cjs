// Read-only axe scan of the newer screens (smart dashboard, teams, explore, API, datasource forms) in
// every theme. Usage: OPENREPORTING_UI_URL, UI_TEST_USER, UI_TEST_PASSWORD, OPENREPORTING_UI_SMART (uid).
const { chromium } = require(process.env.OPENREPORTING_PLAYWRIGHT_MODULE || 'playwright');
const AxeBuilder = require(process.env.OPENREPORTING_AXE_MODULE || '@axe-core/playwright').default;
const assert = require('node:assert/strict');
const { THEMES, applyTheme } = require('./themes.cjs');

const base = process.env.OPENREPORTING_UI_URL || 'http://127.0.0.1:8811';
(async () => {
  assert.ok(process.env.UI_TEST_USER && process.env.UI_TEST_PASSWORD, 'Set UI_TEST_USER and UI_TEST_PASSWORD');
  const browser = await chromium.launch({ headless: true });
  const failures = [];
  const errors = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const login = await context.request.post(`${base}/api/login`, { data: { username: process.env.UI_TEST_USER, password: process.env.UI_TEST_PASSWORD } });
    assert.equal(login.status(), 200);
    const page = await context.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    const routes = ['/smart', '/admin/teams', '/explore', '/admin/api', '/admin/api-keys', '/datasources/new'];
    if (process.env.OPENREPORTING_UI_SMART) routes.push(`/smart/${process.env.OPENREPORTING_UI_SMART}`);
    for (const route of routes) {
      await page.goto(base + route);
      await page.locator('.app-shell').waitFor();
      await page.waitForLoadState('networkidle');
      for (const theme of THEMES) {
        await applyTheme(page, theme);
        const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
        for (const v of result.violations.filter((x) => ['serious', 'critical'].includes(x.impact))) {
          failures.push(`${route}/${theme.id}: ${v.id} → ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`);
        }
      }
      console.log(`scanned ${route}`);
    }
  } finally {
    await browser.close();
  }
  console.log(failures.length ? failures.join('\n') : 'no serious/critical findings');
  assert.deepEqual(errors, [], 'No page errors');
  assert.deepEqual(failures, []);
})().catch((err) => { console.error(err.message); process.exit(1); });
