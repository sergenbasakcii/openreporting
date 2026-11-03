// Mutating acceptance MUST use tools/mfa_browser_acceptance.py's disposable fixture.
const { chromium } = require(process.env.OPENREPORTING_PLAYWRIGHT_MODULE || 'playwright');
const AxeBuilder = require(process.env.OPENREPORTING_AXE_MODULE || '@axe-core/playwright').default;
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { THEMES, applyTheme } = require('./themes.cjs');
const fs = require('node:fs');
assert.equal(process.env.OPENREPORTING_MFA_DISPOSABLE, 'true', 'Use the disposable fixture launcher');
const base = process.env.OPENREPORTING_UI_URL;
assert.match(base, /^http:\/\/127\.0\.0\.1:\d+$/);
const password = process.env.UI_TEST_PASSWORD;
const results = [];
function totp(secret) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const bits = [...secret].map(c => alphabet.indexOf(c).toString(2).padStart(5, '0')).join('');
  const key = Buffer.from(bits.match(/.{8}/g).map(b => parseInt(b, 2)));
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = crypto.createHmac('sha1', key).update(counter).digest();
  return String((digest.readUInt32BE(digest.at(-1) & 15) & 0x7fffffff) % 1000000).padStart(6, '0');
}
(async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    async function scan(stage) {
      console.log(`MFA UI check: ${stage}`);
      for (const { id: theme, scheme } of THEMES) {
        await applyTheme(page, { id: theme, scheme });
        const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice']).analyze();
        // Never save full axe node HTML: this page can contain one-time secrets.
        const violations = result.violations.map(v => ({ id: v.id, impact: v.impact, count: v.nodes.length }));
        results.push({ stage, theme, violations });
        // Selectors only (no node HTML) so a failure names the element without exposing secrets.
        const where = result.violations.flatMap(v => v.nodes.map(n => `${v.id}: ${n.target.join(' ')} (${(n.failureSummary || '').replace(/\s+/g, ' ').slice(0, 300)})`));
        assert.deepEqual(violations, [], `${stage}/${theme} ${where.join('; ')}`);
      }
    }
    async function login(name, code) {
      console.log(`MFA UI sign-in: ${name}, additional proof ${Boolean(code)}`);
      await page.goto(base + '/profile');
      await page.getByLabel('Kullanıcı adı', { exact: true }).fill(name);
      await page.getByLabel('Parola', { exact: true }).fill(password);
      // Initial autofocus must not move typing back into the username field.
      await page.waitForTimeout(40);
      assert.ok(await page.getByLabel('Parola', { exact: true }).evaluate(el => el === document.activeElement), 'Password keeps keyboard focus');
      assert.ok(await page.getByLabel('Parola', { exact: true }).inputValue() === password, 'Password fill completed');
      const first = page.waitForResponse(response => response.url().endsWith('/api/login'));
      await page.getByRole('button', { name: 'Giriş yap', exact: true }).click();
      const response = await first;
      const sent = response.request().postDataJSON();
      assert.ok(sent.username === name, 'Fixture username must reach the current login form');
      assert.ok(sent.password === password, `Fixture password must reach the current login form (length ${sent.password?.length}, expected ${password.length})`);
      const data = await response.json();
      console.log(`MFA UI sign-in response: ${response.status()}, challenge ${data.detail?.code || 'none'}`);
      if (code) {
        await page.getByRole('alert').waitFor();
        const alert = await page.getByRole('alert').innerText();
        assert.equal(alert, 'Devam etmek için doğrulayıcı veya kurtarma kodunuzu girin.', `Factor prompt: ${alert}`);
        const input = page.getByLabel('Doğrulayıcı veya kurtarma kodu', { exact: true });
        await input.fill(code);
        await page.getByRole('button', { name: 'Giriş yap', exact: true }).click();
      }
    }
    async function setup(simulateExpiry = false) {
      await page.getByRole('button', { name: 'İki adımlı girişi kur', exact: true }).click();
      await scan('setup-password');
      const dialog = page.getByRole('dialog');
      await dialog.getByLabel('Mevcut parola', { exact: true }).fill(password);
      await dialog.getByRole('button', { name: 'Kurulumu başlat', exact: true }).click();
      // Enrollment is QR first; the manual key is a collapsed fallback grouped by four characters.
      await dialog.getByRole('img', { name: 'Doğrulayıcı uygulaması için QR kod' }).waitFor();
      assert.ok((await dialog.locator('.mfa-qr img').getAttribute('src')).startsWith('data:image/svg+xml'), 'QR is an inline SVG');
      const readSecret = async () => (await dialog.getByLabel('Kurulum anahtarı', { exact: true }).inputValue()).replace(/\s/g, '');
      let secret = await readSecret();
      await scan('setup-confirm');
      let codeField = dialog.getByLabel('2. Uygulamada görünen 6 haneli kod', { exact: true });
      if (simulateExpiry) {
        // An expired enrollment offers a fresh QR in place instead of a dead end.
        await page.route('**/api/user/mfa/confirm', route => route.fulfill({ status: 409, contentType: 'application/json', body: '{"detail":"Setup expired"}' }), { times: 1 });
        await codeField.fill('000000');
        await dialog.getByRole('button', { name: 'Kurulumu onayla', exact: true }).click();
        await dialog.getByRole('button', { name: 'Yeni QR kod al', exact: true }).click();
        await dialog.getByRole('img', { name: 'Doğrulayıcı uygulaması için QR kod' }).waitFor();
        const renewedSecret = await readSecret();
        assert.notEqual(renewedSecret, secret, 'Expired setup issues a new key');
        secret = renewedSecret;
        codeField = dialog.getByLabel('2. Uygulamada görünen 6 haneli kod', { exact: true });
      }
      await codeField.fill('KEY-not-a-code');
      assert.equal(await codeField.inputValue(), '', 'Only digits are accepted');
      await codeField.fill(totp(secret));
      await dialog.getByRole('button', { name: 'Kurulumu onayla', exact: true }).click();
      await page.getByRole('heading', { name: 'Kurtarma kodlarını saklayın' }).waitFor();
      await scan('recovery-once');
      const codes = (await page.locator('.mfa-codes').innerText()).split('\n');
      assert.equal(codes.length, 10);
      await page.getByRole('button', { name: 'Giriş ekranına dön', exact: true }).click();
      await page.locator('.login-page form').waitFor();
      return codes;
    }
    await login('optionaluser');
    await page.getByRole('heading', { name: 'İki adımlı giriş', exact: true }).waitFor();
    await scan('optional-profile');
    const codes = await setup(true);
    await login('optionaluser', codes[0]);
    await page.getByRole('button', { name: 'Kurtarma kodlarını yenile', exact: true }).waitFor();
    await scan('enabled-profile');
    await page.getByRole('button', { name: 'Kurtarma kodlarını yenile', exact: true }).click();
    let dialog = page.getByRole('dialog');
    await dialog.getByLabel('Mevcut parola', { exact: true }).fill(password);
    await dialog.getByLabel('Doğrulayıcı veya kurtarma kodu', { exact: true }).fill(codes[1]);
    await dialog.getByRole('button', { name: 'Kodları yenile', exact: true }).click();
    await page.getByRole('heading', { name: 'Kurtarma kodlarını saklayın' }).waitFor();
    const renewed = (await page.locator('.mfa-codes').innerText()).split('\n');
    assert.notDeepEqual(renewed, codes);
    await page.getByRole('button', { name: 'Giriş ekranına dön', exact: true }).click();
    await page.locator('.login-page form').waitFor();
    await login('optionaluser', renewed[0]);
    await page.getByRole('button', { name: 'Kapat', exact: true }).click();
    dialog = page.getByRole('dialog');
    await dialog.getByLabel('Mevcut parola', { exact: true }).fill(password);
    await dialog.getByLabel('Doğrulayıcı veya kurtarma kodu', { exact: true }).fill(renewed[1]);
    await dialog.getByRole('button', { name: 'İki adımlı girişi kapat', exact: true }).click();
    await page.getByRole('heading', { name: 'İki adımlı giriş kapatıldı' }).waitFor();
    await scan('disabled');
    await page.getByRole('button', { name: 'Giriş ekranına dön', exact: true }).click();
    await page.locator('.login-page form').waitFor();
    await login('optionaluser');
    await page.getByRole('heading', { name: 'İki adımlı giriş', exact: true }).waitFor();
    // Old server fallback: a missing endpoint must not break the existing profile.
    await page.route('**/api/user/mfa', route => route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not Found"}' }));
    await page.reload();
    await page.getByRole('heading', { name: 'Tercihler', exact: true }).waitFor();
    assert.equal(await page.getByRole('heading', { name: 'İki adımlı giriş', exact: true }).count(), 0);
    await page.unroute('**/api/user/mfa');
    // Fresh context avoids inheriting the optional user's cookie/session.
    await context.clearCookies();
    const requests = [];
    page.on('request', request => { if (request.url().includes('/api/')) requests.push(new URL(request.url()).pathname); });
    await login('requireduser');
    await page.getByRole('heading', { name: 'İki adımlı giriş gerekli', exact: true }).waitFor();
    assert.ok(!requests.includes('/api/user') && !requests.includes('/api/frontend/settings'));
    await scan('required-gate');
    const mandatory = await setup();
    await login('requireduser', mandatory[0]);
    await page.getByRole('button', { name: 'Kurtarma kodlarını yenile', exact: true }).waitFor();
    assert.deepEqual(errors, []);
    fs.mkdirSync('build', { recursive: true });
    fs.writeFileSync('build/mfa-browser-evidence.json', JSON.stringify({ ok: true, scans: results.length, results, pageErrors: errors }, null, 2));
    console.log(`MFA optional/required enrollment, expired-setup restart, recovery rotation, disable, old-server fallback: passed; ${results.length} theme/accessibility scans clean`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exit(1); });
