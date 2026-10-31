// Mutate only tools/folder_browser_acceptance.py's owned disposable fixture.
const { chromium } = require(process.env.OPENREPORTING_PLAYWRIGHT_MODULE || 'playwright');
const AxeBuilder = require(process.env.OPENREPORTING_AXE_MODULE || '@axe-core/playwright').default;
const assert = require('node:assert/strict');
const fs = require('node:fs');
assert.equal(process.env.OPENREPORTING_FOLDER_DISPOSABLE, 'true');
const base = process.env.OPENREPORTING_UI_URL;
assert.match(base, /^http:\/\/127\.0\.0\.1:\d+$/);
(async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [], results = [];
  try {
    async function login(username) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      const response = await context.request.post(base + '/api/login', { data: { username, password: process.env.UI_TEST_PASSWORD } });
      assert.equal(response.status(), 200);
      const page = await context.newPage(); page.on('pageerror', e => errors.push(e.message));
      await page.goto(base + '/dashboards');
      return { context, page };
    }
    async function scan(page, stage) {
      for (const theme of ['dark', 'light']) {
        await page.evaluate(t => { document.documentElement.dataset.theme = t; }, theme);
        const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice']).analyze();
        const violations = result.violations.map(v => ({ id: v.id, impact: v.impact, count: v.nodes.length }));
        results.push({ stage, theme, violations }); assert.deepEqual(violations, [], `${stage}/${theme}`);
      }
    }
    const { context, page } = await login('folderadmin');
    await page.getByRole('button', { name: 'Browser folder klasör işlemleri' }).click();
    await page.getByText('Klasör izinleri', { exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Klasör izinleri: Browser folder' });
    await dialog.waitFor(); await scan(page, 'shared-policy-dialog');
    await dialog.getByText('Klasör erişimini kısıtla', { exact: true }).click();
    await dialog.getByLabel('foldereditor (editor)', { exact: true }).selectOption('view');
    assert.equal(await dialog.getByLabel('folderviewer (viewer)', { exact: true }).inputValue(), 'edit');
    await dialog.getByLabel('folderviewer (viewer)', { exact: true }).selectOption('');
    assert.equal(await dialog.getByText('inactiveuser (viewer)', { exact: true }).count(), 0);
    await scan(page, 'restricted-policy-dialog');
    const saved = page.waitForResponse(r => /\/permissions$/.test(r.url()) && r.request().method() === 'PUT');
    await dialog.getByRole('button', { name: 'Kaydet', exact: true }).click();
    assert.equal((await saved).status(), 200);
    const editor = await login('foldereditor');
    await editor.page.getByRole('link', { name: /Folder UI content/ }).click();
    await editor.page.getByText('Folder UI content', { exact: true }).first().waitFor();
    assert.equal(await editor.page.getByRole('button', { name: 'Kaydet', exact: true }).count(), 0);
    assert.equal(await editor.page.getByRole('button', { name: 'Dashboard ayarları', exact: true }).count(), 0);
    await scan(editor.page, 'editor-view-only-dashboard');
    const viewer = await login('folderviewer');
    await viewer.page.getByRole('heading', { name: 'Dashboard’lar', exact: true }).waitFor();
    assert.equal(await viewer.page.getByText('Folder UI content', { exact: true }).count(), 0);
    await viewer.page.goto(base + '/d/folder-ui');
    await viewer.page.getByText('İçerik bulunamadı veya erişim izniniz yok', { exact: true }).waitFor();
    await scan(viewer.page, 'denied-direct-link');
    // Old backends have no flag: current static files must not offer an unsupported policy editor.
    const old = await login('folderadmin');
    await old.page.route('**/api/frontend/settings', async route => {
      const response = await route.fetch(); const data = await response.json(); delete data.features.folderAcl;
      await route.fulfill({ response, json: data });
    });
    await old.page.reload();
    await old.page.getByRole('button', { name: 'Browser folder klasör işlemleri' }).click();
    assert.equal(await old.page.getByText('Klasör izinleri', { exact: true }).count(), 0);
    assert.deepEqual(errors, []);
    fs.mkdirSync('build', { recursive: true });
    fs.writeFileSync('build/folder-browser-evidence.json', JSON.stringify({ ok: true, scans: results.length, results, pageErrors: errors }, null, 2));
    console.log(`Folder grants, view-only controls, denied links and old-server fallback passed; ${results.length} accessibility/theme scans clean`);
    await context.close(); await editor.context.close(); await viewer.context.close(); await old.context.close();
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exit(1); });
