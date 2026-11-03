// Read-only acceptance scan. Install @axe-core/playwright only in a QA directory.
// Synthetic preview credentials come from env; nothing is saved in the product.
const { chromium } = require(process.env.OPENREPORTING_PLAYWRIGHT_MODULE || 'playwright');
const AxeBuilder = require(process.env.OPENREPORTING_AXE_MODULE || '@axe-core/playwright').default;
const assert = require('node:assert/strict');
const { THEMES, applyTheme } = require('./themes.cjs');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.OPENREPORTING_UI_URL || 'http://127.0.0.1:8811';
const uid = encodeURIComponent(process.env.OPENREPORTING_UI_DASHBOARD || 'preview');
const output = process.env.OPENREPORTING_A11Y_OUTPUT || 'build/a11y-report.json';

(async () => {
  assert.ok(process.env.UI_TEST_USER && process.env.UI_TEST_PASSWORD, 'Set UI_TEST_USER and UI_TEST_PASSWORD');
  const browser = await chromium.launch({ headless: true });
  const results = [];
  const errors = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    async function scan(route, theme) {
      const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']).analyze();
      results.push({ page: route, theme, ...result });
      console.log(JSON.stringify({ route, theme, violations: result.violations.map(v => ({ id: v.id, impact: v.impact, count: v.nodes.length })) }));
    }
    await page.goto(`${base}/`);
    await page.locator('.login-page').waitFor();
    await scan('login', 'dark');
    const login = await context.request.post(`${base}/api/login`, { data: { username: process.env.UI_TEST_USER, password: process.env.UI_TEST_PASSWORD } });
    assert.equal(login.status(), 200);
    for (const route of [`/d/${uid}`, '/dashboards', '/datasources/new', `/reports/new?dashboard=${uid}`, '/admin/server', '/profile', `/d/${uid}?editPanel=1`, '/admin/users']) {
      await page.goto(base + route);
      await page.locator('.app-shell').waitFor();
      await page.waitForLoadState('networkidle');
      for (const theme of THEMES) {
        await applyTheme(page, theme);
        await scan(route, theme.id);
      }
    }
    // Actual user dialog: Tab wraps, Escape cancels and restores the opener.
    const opener = page.getByRole('button', { name: 'Kullanıcı ekle', exact: true });
    await opener.click();
    await page.getByRole('dialog').waitFor();
    await page.waitForFunction(() => document.querySelector('[role="dialog"]')?.contains(document.activeElement));
    const focusables = page.getByRole('dialog').locator('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled])');
    await focusables.last().focus();
    await page.keyboard.press('Tab');
    assert.equal(await focusables.first().evaluate(el => el === document.activeElement), true);
    await page.keyboard.press('Shift+Tab');
    assert.equal(await focusables.last().evaluate(el => el === document.activeElement), true);
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('dialog').count(), 0);
    assert.equal(await opener.evaluate(el => el === document.activeElement), true);
    // Actual panel menu: arrows and Home/End navigate, Escape restores focus.
    await page.goto(`${base}/d/${uid}`);
    const panelMenu = page.locator('.panel').first().getByRole('button', { name: 'Panel menüsü', exact: true });
    await panelMenu.click();
    const items = page.getByRole('menuitem');
    await page.keyboard.press('End');
    assert.equal(await items.last().evaluate(el => el === document.activeElement), true);
    await page.keyboard.press('ArrowDown');
    assert.equal(await items.first().evaluate(el => el === document.activeElement), true);
    await page.keyboard.press('Escape');
    assert.equal(await panelMenu.evaluate(el => el === document.activeElement), true);
    await page.goto(`${base}/d/${uid}?editPanel=1`);
    const section = page.locator('.sec-head').first();
    await section.focus();
    const wasExpanded = await section.getAttribute('aria-expanded');
    await page.keyboard.press('Space');
    assert.equal(await section.getAttribute('aria-expanded'), String(wasExpanded !== 'true'));
    await page.keyboard.press('Enter');
    assert.equal(await section.getAttribute('aria-expanded'), wasExpanded);
    console.log('Dialog focus trap/cancel, menu navigation and panel section keyboard controls passed');
    assert.deepEqual(errors, [], 'No page errors');
    const failures = results.flatMap(r => r.violations.filter(v => ['critical', 'serious'].includes(v.impact)).map(v => `${r.page}/${r.theme}: ${v.id}`));
    assert.deepEqual(failures, [], 'Resolve critical/serious automated findings; manual acceptance is still required');
  } finally {
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, JSON.stringify(results, null, 2));
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
