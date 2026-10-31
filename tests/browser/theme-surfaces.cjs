// Read-only browser acceptance check against a running local preview.
// Credentials come from env; no users, sources, dashboards or preferences are saved.
const { chromium } = require(process.env.OPENREPORTING_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.OPENREPORTING_UI_URL || 'http://127.0.0.1:8811';
const uid = process.env.OPENREPORTING_UI_DASHBOARD || 'preview';
const output = process.env.OPENREPORTING_UI_OUTPUT || 'build/theme-audit';

(async () => {
  assert.ok(process.env.UI_TEST_USER && process.env.UI_TEST_PASSWORD, 'Set UI_TEST_USER and UI_TEST_PASSWORD');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
    const login = await context.request.post(`${base}/api/login`, { data: { username: process.env.UI_TEST_USER, password: process.env.UI_TEST_PASSWORD } });
    assert.equal(login.status(), 200);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    let queries = 0;
    page.on('request', req => { if (new URL(req.url()).pathname === '/api/ds/query') queries += 1; });
    const dashboardUrl = `${base}/d/${encodeURIComponent(uid)}`;
    async function theme(value) {
      await page.locator('.app-shell').waitFor();
      await page.evaluate(value => {
        document.documentElement.dataset.theme = value;
        window.dispatchEvent(new CustomEvent('openreporting:themechange', { detail: value }));
      }, value);
    }
    async function surface(selector, variable = '--bg-elevated') {
      const result = await page.locator(selector).first().evaluate((el, variable) => {
        const probe = document.createElement('span');
        probe.style.backgroundColor = `var(${variable})`;
        document.body.append(probe);
        const expected = getComputedStyle(probe).backgroundColor;
        probe.remove();
        return { actual: getComputedStyle(el).backgroundColor, expected };
      }, variable);
      assert.equal(result.actual, result.expected, `${selector} must use ${variable}`);
    }
    async function selects() {
      const failures = await page.locator('select').evaluateAll(items => {
        const probe = document.createElement('span');
        probe.style.backgroundColor = 'var(--bg-elevated)';
        document.body.append(probe);
        const expected = getComputedStyle(probe).backgroundColor;
        const scheme = document.documentElement.dataset.theme;
        const failed = [];
        for (const el of items) {
          if (getComputedStyle(el).colorScheme !== scheme) failed.push('native color scheme');
          for (const option of el.querySelectorAll('option')) {
            if (!option.selected && getComputedStyle(option).backgroundColor !== expected) failed.push(option.textContent);
          }
        }
        probe.remove();
        return failed;
      });
      assert.deepEqual(failures, []);
    }

    for (const mode of ['dark', 'light']) {
      await page.goto(dashboardUrl);
      await page.locator('.panel').first().waitFor();
      await page.waitForFunction(() => !document.querySelector('.panel-loading:not([hidden])'));
      const before = queries;
      await theme(mode);
      await page.waitForTimeout(100);
      assert.equal(queries, before, 'Theme changes must use cached data');
      for (const label of ['Zaman aralığı', 'Otomatik yenileme', 'Diğer']) {
        const control = label === 'Zaman aralığı' ? page.getByTitle(label, { exact: true }) : page.getByRole('button', { name: label, exact: true });
        await control.first().click();
        await surface('.menu');
        await page.keyboard.press('Escape');
      }
      const firstPanel = page.locator('.panel').first();
      await firstPanel.getByRole('button', { name: 'Panel menüsü' }).click();
      await surface('.menu');
      await page.getByRole('menuitem', { name: /^Görüntüle/ }).click();
      await page.locator('.view-panel-mode').waitFor();
      await surface('body', '--bg');
      await page.getByRole('button', { name: 'Dashboard’a dön', exact: true }).click();
      await page.waitForFunction(() => [...document.querySelectorAll('.panel')].every(el =>
        el.querySelector('.viz')?.children.length && el.querySelector('.panel-loading').hidden));
      await page.locator('.panel').first().getByRole('button', { name: 'Panel menüsü' }).click();
      await page.getByRole('menuitem', { name: /^İncele \(veri \/ sorgu\)/ }).click();
      await surface('.modal');
      await page.screenshot({ path: `${output}/inspector-${mode}.png` });
      await page.keyboard.press('Escape');

      for (const route of ['/dashboards', '/datasources/new', `/reports/new?dashboard=${encodeURIComponent(uid)}`, '/profile', `/d/${uid}?editPanel=1`]) {
        await page.goto(base + route);
        await page.locator('select').first().waitFor();
        await theme(mode);
        await selects();
      }
      // Exercise a native popup without changing its selection.
      await page.goto(`${base}/datasources/new`);
      await page.locator('select').first().waitFor();
      await theme(mode);
      await page.locator('select').first().click();
      assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), mode);
      await page.screenshot({ path: `${output}/select-${mode}.png` });
      await page.keyboard.press('Escape');

      // Hold the real preview request to inspect its loading window before navigation.
      await page.goto(`${base}/reports/new?dashboard=${encodeURIComponent(uid)}`);
      await page.getByRole('button', { name: 'PDF önizle', exact: true }).waitFor();
      await theme(mode);
      let release;
      const gate = new Promise(resolve => { release = resolve; });
      await page.route('**/api/dash-reports/preview', async route => { await gate; await route.continue(); });
      const popupPromise = page.waitForEvent('popup');
      await page.getByRole('button', { name: 'PDF önizle', exact: true }).click();
      const popup = await popupPromise;
      await popup.getByRole('status').waitFor();
      assert.equal(await popup.evaluate(() => document.documentElement.dataset.theme), mode);
      assert.equal(await popup.evaluate(() => window.opener), null);
      const color = await popup.locator('body').evaluate(el => getComputedStyle(el).backgroundColor);
      assert.equal(color, mode === 'dark' ? 'rgb(17, 18, 23)' : 'rgb(244, 245, 245)');
      await popup.screenshot({ path: `${output}/preview-${mode}.png` });
      const navigation = popup.waitForURL(url => url.protocol === 'blob:', { timeout: 30000, waitUntil: 'commit' });
      const download = popup.waitForEvent('download', { timeout: 30000 }).then(async file => {
        assert.equal(await file.failure(), null);
      });
      release();
      // Headless Chromium downloads PDFs instead of opening its native PDF viewer.
      await Promise.any([navigation, download]);
      await popup.close();
      await page.unroute('**/api/dash-reports/preview');
    }

    // All 20 new renderers must replace cached canvas tooltips on a theme change.
    const chartAudit = await page.evaluate(async () => {
      const { PanelView } = await import('/static/app/dashboard/panelview.js');
      const { EXTRA_NAMES } = await import('/static/app/panels/extended.js');
      const { newPanel } = await import('/static/app/panels/registry.js');
      const series = [1, 2, 3].map(i => ({ type:'timeseries', name:`Test ${i}`, labels:{group:`G${i}`}, points:[[1000, i],[2000, i+1]] }));
      const table = { type:'table', columns:[{name:'name',type:'string'},...['open','close','low','high'].map(name=>({name,type:'number'}))],rows:[['A',10,12,8,15],['B',12,9,7,16]] };
      const graph = { type:'table', columns:[{name:'source',type:'string'},{name:'target',type:'string'},{name:'value',type:'number'}],rows:[['A','B',10],['B','C',5]] };
      const gallery = document.createElement('div');
      gallery.style.cssText = 'display:grid;grid-template-columns:repeat(3,380px);gap:8px;position:fixed;left:0;top:0;z-index:9999;max-height:95vh;overflow:auto;background:var(--bg)';
      document.body.append(gallery);
      const views = [];
      try {
        for (const [i,type] of Object.keys(EXTRA_NAMES).entries()) {
          const panel = newPanel(type,i+1,{});
          panel.title = type;
          const view = new PanelView(panel,{variables:{},scopedVars:{},timezone:'UTC'});
          view.el.style.cssText = 'position:relative;height:250px';
          gallery.append(view.el);
          view.frames = ['scatter','bubble','boxplot','candlestick','parallel'].includes(type) ? [table] : ['sankey','nodegraph'].includes(type) ? [graph] : series;
          views.push(view);
          view.render();
        }
        const failures = [];
        for (const mode of ['dark','light']) {
          const oldCharts = views.map(view=>view.viz?.chart);
          document.documentElement.dataset.theme = mode;
          window.dispatchEvent(new CustomEvent('openreporting:themechange'));
          const expected = getComputedStyle(document.documentElement).getPropertyValue('--bg-elevated').trim();
          for (const view of views) {
            const chart = view.viz?.chart;
            if (!chart || chart.getOption().tooltip[0].backgroundColor !== expected) failures.push(`${mode}:${view.panel.type}`);
          }
          if (oldCharts.some(chart=>chart && !chart.isDisposed())) failures.push('old canvas not disposed');
        }
        return { count:views.length, failures };
      } finally {
        views.forEach(view=>view.destroy());
        gallery.remove();
      }
    });
    assert.equal(chartAudit.count,20);
    assert.deepEqual(chartAudit.failures,[]);

    // Use the actual profile control for system-theme change propagation.
    await page.goto(`${base}/profile`);
    await page.emulateMedia({ colorScheme: 'light' });
    await page.getByLabel('Tema', { exact: true }).selectOption('system');
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'light');
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    assert.deepEqual(errors, []);
    console.log('Dark/light native selects, menus, panel view/inspector, PDF loading, all 20 chart tooltips, cached rerender and system theme passed');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
