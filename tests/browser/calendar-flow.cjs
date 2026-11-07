// Date-range calendar: pick a range on the report form and in the dashboard time picker, by mouse and keyboard,
// and scan the open calendar with axe in every theme. Usage: OPENREPORTING_UI_URL, UI_TEST_USER, UI_TEST_PASSWORD.
const { chromium } = require(process.env.OPENREPORTING_PLAYWRIGHT_MODULE || 'playwright');
const AxeBuilder = require(process.env.OPENREPORTING_AXE_MODULE || '@axe-core/playwright').default;
const assert = require('node:assert/strict');
const { THEMES, applyTheme } = require('./themes.cjs');

const base = process.env.OPENREPORTING_UI_URL || 'http://127.0.0.1:8811';
const out = process.env.OPENREPORTING_UI_OUTPUT || 'build/calendar';
(async () => {
  assert.ok(process.env.UI_TEST_USER && process.env.UI_TEST_PASSWORD, 'Set UI_TEST_USER and UI_TEST_PASSWORD');
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 950 }, timezoneId: 'Europe/Istanbul' });
    const login = await context.request.post(`${base}/api/login`, { data: { username: process.env.UI_TEST_USER, password: process.env.UI_TEST_PASSWORD } });
    assert.equal(login.status(), 200);
    const page = await context.newPage();
    page.on('pageerror', (e) => errors.push(e.message));

    // Report form: open, pick the 1st and 10th of the left month with the mouse, apply.
    await page.goto(`${base}/reports/new`);
    await page.getByRole('button', { name: 'Takvim' }).click();
    const cal = page.locator('.cal');
    await cal.waitFor();
    // "Dün" (now-1d/d) opens as a whole-day selection.
    assert.equal(await cal.locator('.cal-times input[type=checkbox]').isChecked(), true);
    assert.match(await cal.locator('.cal-summary').innerText(), /1 gün/);
    const leftMonth = cal.locator('.cal-month').first();
    const title = await leftMonth.locator('.cal-title').innerText();
    await leftMonth.locator('.cal-day', { hasText: /^1$/ }).first().click();
    await leftMonth.locator('.cal-day', { hasText: /^10$/ }).first().click();
    assert.match(await cal.locator('.cal-summary').innerText(), /10 gün/);
    assert.equal(await cal.locator('.cal-day.in').count(), 8);
    await page.screenshot({ path: `${out}/report-calendar.png` });
    for (const theme of THEMES) {
      await applyTheme(page, theme);
      const result = await new AxeBuilder({ page }).include('.cal').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
      const serious = result.violations.filter((v) => ['serious', 'critical'].includes(v.impact));
      assert.deepEqual(serious.map((v) => `${theme.id}: ${v.id}`), []);
    }
    await cal.getByRole('button', { name: 'Uygula' }).click();
    await cal.waitFor({ state: 'detached' });
    const [monthName, year] = title.split(' ');
    const months = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
    const mm = String(months.indexOf(monthName) + 1).padStart(2, '0');
    const inputs = page.locator('.form-grid input.input');
    const values = await inputs.evaluateAll((els) => els.map((e) => e.value));
    assert.ok(values.includes(`${year}-${mm}-01 00:00:00`), `start shown as wall-clock date: ${values}`);
    assert.ok(values.includes(`${year}-${mm}-11 00:00:00`), `end is the next midnight: ${values}`);

    // Keyboard: reopen, move with arrows, pick with Enter twice.
    await page.getByRole('button', { name: 'Takvim' }).click();
    await page.locator('.cal').waitFor();
    await page.waitForFunction(() => document.activeElement?.classList.contains('cal-day'));
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('Enter');
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('Enter');
    assert.match(await page.locator('.cal-summary').innerText(), /3 gün/);
    await page.keyboard.press('Escape');

    // Typed relative and invalid values.
    const fromIn = inputs.nth(0);
    await fromIn.fill('now-7d/d'); await fromIn.press('Tab');
    assert.equal(await fromIn.inputValue(), 'now-7d/d');
    await fromIn.fill('31.02.2026'); await fromIn.press('Tab');
    await page.locator('.toast').filter({ hasText: 'Geçersiz zaman' }).first().waitFor();

    // Dashboard time picker: "Takvimden seç" changes the URL range to absolute epochs.
    await page.goto(`${base}/dashboards/new`);
    await page.getByTitle('Zaman aralığı', { exact: true }).first().click();
    await page.getByRole('button', { name: 'Takvimden seç' }).click();
    const dashCal = page.locator('.cal');
    await dashCal.waitFor();
    const left = dashCal.locator('.cal-month').first();
    await left.locator('.cal-day', { hasText: /^3$/ }).first().click();
    await left.locator('.cal-day', { hasText: /^4$/ }).first().click();
    await dashCal.getByRole('button', { name: 'Uygula' }).click();
    await page.waitForFunction(() => /from=\d{13}/.test(location.search) && /to=\d{13}/.test(location.search));
    await page.screenshot({ path: `${out}/dashboard-after-pick.png` });
    // Picked days from a relative range ("Son 6 saat") are whole days: 3rd 00:00 → 5th 00:00 in the time zone.
    const params = await page.evaluate(() => Object.fromEntries(new URLSearchParams(location.search)));
    const span = (Number(params.to) - Number(params.from)) / 3600000;
    assert.ok(span === 48, `two whole days expected, got ${span} h`);
    const startHour = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit' }).format(new Date(Number(params.from)));
    assert.equal(startHour, '00:00');
  } finally {
    await browser.close();
  }
  assert.deepEqual(errors, [], 'No page errors');
  console.log('Calendar: mouse and keyboard range picking, report and dashboard wiring, typed values and axe in every theme passed');
})().catch((err) => { console.error(err); process.exit(1); });
