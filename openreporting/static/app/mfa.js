// Own-account factor setup. Secrets stay in this form only, never URL or browser storage.
import { h, button, input, field, modal } from './dom.js';
import { get, post, setCsrf } from './api.js';

function completed(result) {
  // Stop page timers and close all old overlays before presenting one-time recovery material.
  window.dispatchEvent(new Event('openreporting:factorchanged'));
  setCsrf('');
  const codes = result.recovery_codes;
  const content = h('main', { class: 'login-page' }, h('div', { class: 'login-card' },
    h('h1', { text: codes ? 'Kurtarma kodlarını saklayın' : 'İki adımlı giriş kapatıldı' }),
    h('p', { text: codes ? 'Bu kodlar yalnız bu ekranda gösterilir. Her kod bir kez kullanılabilir. Cihazınıza erişemediğinizde parolanızla birlikte kullanın; güvenli ve ayrı bir yerde saklayın.' : 'Tüm oturumlar kapatıldı. Kurum politikası gerektiriyorsa tekrar kurulum istenir.' }),
    codes ? h('pre', { class: 'mfa-codes', text: codes.join('\n'), role: 'region', tabindex: '0', 'aria-label': 'Tek kullanımlık kurtarma kodları' }) : null,
    h('p', { class: 'hint', text: 'Yeniden girişte, az önce kullandığınız kod yerine sonraki 30 saniyelik kodu bekleyin veya bir kurtarma kodu kullanın.' }),
    button('Giriş ekranına dön', { variant: 'primary', onClick: () => location.reload() })));
  document.getElementById('app').replaceChildren(content);
  content.querySelector('button').focus();
}

function factorDialog(action) {
  const setup = action === 'setup';
  let pending = null;
  let alive = true;
  const password = input({ type: 'password', autocomplete: 'current-password', required: true, maxlength: 1024 });
  const code = input({ autocomplete: 'one-time-code', required: true, maxlength: 128 });
  // Enrollment confirms with the app's current 6-digit code only (recovery codes do not exist yet).
  const setupCode = input({ autocomplete: 'one-time-code', required: true, maxlength: 6, placeholder: '123456',
    onInput: (e) => { e.target.value = e.target.value.replace(/\D/g, '').slice(0, 6); } });
  setupCode.setAttribute('inputmode', 'numeric');
  setupCode.setAttribute('pattern', '[0-9]{6}');
  setupCode.classList.add('mfa-code');
  const error = h('div', { class: 'alert error', role: 'alert', hidden: true });
  const stage = h('div');
  const submit = button(setup ? 'Kurulumu başlat' : action === 'disable' ? 'İki adımlı girişi kapat' : 'Kodları yenile', { variant: 'primary', type: 'submit' });
  const form = h('form', { onsubmit: async (e) => {
    e.preventDefault(); submit.disabled = true; error.hidden = true;
    try {
      if (setup && !pending) {
        const data = await post('/api/user/mfa/setup', { password: password.value });
        if (!alive) return;
        pending = data;
        const grouped = data.secret.replace(/(.{4})/g, '$1 ').trim();
        stage.replaceChildren(
          h('p', { text: '1. Telefonunuzdaki doğrulayıcı uygulamasıyla (Google Authenticator, Microsoft Authenticator vb.) bu QR kodu okutun.' }),
          h('div', { class: 'mfa-qr' }, h('img', { src: data.qr, alt: 'Doğrulayıcı uygulaması için QR kod', width: 200, height: 200 })),
          h('details', { class: 'mfa-manual' }, h('summary', { text: 'QR kodu okutamıyor musunuz? Anahtarı elle girin' }),
            h('p', { class: 'hint', text: 'Uygulamada "Kurulum anahtarı gir" seçin; tür: zamana dayalı. Anahtar yalnız A–Z harfleri ve 2–7 rakamlarından oluşur (0, 1, 8, 9 yoktur).' }),
            input({ value: grouped, readonly: true, class: 'mono', label: 'Kurulum anahtarı' })),
          field('2. Uygulamada görünen 6 haneli kod', setupCode),
          h('p', { class: 'hint', text: `Bu QR kod ${expiryText(data.expires_at)} saatine kadar geçerlidir. Kurtarma kodları onaydan sonra gösterilir.` }));
        submit.textContent = 'Kurulumu onayla'; submit.setAttribute('aria-label', 'Kurulumu onayla'); setupCode.focus();
      } else {
        if (pending && !/^\d{6}$/.test(setupCode.value)) {
          error.textContent = 'Uygulamada görünen 6 haneli sayıyı girin (kurulum anahtarını değil).';
          error.hidden = false;
          setupCode.focus();
          return;
        }
        const body = { password: password.value, code: (pending ? setupCode : code).value.trim() };
        if (pending) body.setup_token = pending.setup_token;
        const result = await post(`/api/user/mfa/${setup ? 'confirm' : action}`, body);
        if (!alive) { location.reload(); return; }
        completed(result);
      }
    } catch (err) {
      if (!alive) return;
      error.textContent = mfaErrorText(err);
      if (pending && err.status === 403) error.textContent += ' Kod kabul edilmiyorsa telefonun saatinin otomatik (ağdan) ayarlı olduğunu kontrol edin.';
      if (pending && err.status === 409) {
        // Expired or replaced enrollment: drop the old QR so the next submit issues a new one.
        pending = null; setupCode.value = ''; stage.replaceChildren();
        submit.textContent = 'Yeni QR kod al'; submit.setAttribute('aria-label', 'Yeni QR kod al');
        error.textContent = 'Kurulum süresi doldu. Yeni QR kod alıp uygulamadaki eski kaydı silerek tekrar okutun.';
      }
      error.hidden = false;
    } finally { if (alive) submit.disabled = false; }
  } },
    h('p', { text: setup ? 'Girişte parolanıza ek bir doğrulayıcı kodu istenir. Önce mevcut parolanızı doğrulayın.' : 'Bu işlem tüm oturumları kapatır. Mevcut parolanız ve yeni bir doğrulayıcı kodu veya kullanılmamış kurtarma kodu gerekir.' }),
    error, field('Mevcut parola', password), stage, submit);
  if (!setup) stage.append(field('Doğrulayıcı veya kurtarma kodu', code));
  const dialog = modal({ title: 'İki adımlı giriş', body: form, closeOnBackdrop: false,
    onClose: () => { alive = false; pending = null; password.value = ''; code.value = ''; setupCode.value = ''; stage.replaceChildren(); } });
  return dialog;
}

function expiryText(iso) {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? '10 dakika sonrası' : at.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
}

// Turkish messages for the second-factor API (its error texts are English).
export function mfaErrorText(err) {
  return ({ 400: 'İki adımlı giriş işlemleri yalnızca HTTPS üzerinden yapılabilir.',
    403: 'Parola veya doğrulama kodu hatalı. Yeni bir kodla tekrar deneyin.',
    409: 'Kurulum süresi doldu veya değişti; baştan başlayın.',
    429: 'Çok fazla deneme yapıldı; 15 dakika sonra tekrar deneyin.' })[err.status] || err.message;
}

export async function mfaCard() {
  let status;
  try { status = await get('/api/user/mfa'); }
  catch (err) {
    // Existing schema-3 previews can still serve these static assets.
    if (err.status === 404) return null;
    return h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'İki adımlı giriş' }), h('p', { role: 'alert', text: 'Güvenlik ayarı şu anda okunamıyor. Sayfayı yenileyin.' }));
  }
  return h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'İki adımlı giriş' }),
    h('p', { text: status.enabled ? `Etkin · ${status.recovery_remaining} kurtarma kodu kaldı.` : 'Kapalı · Doğrulayıcı uygulamayla ek giriş koruması.' }),
    h('div', { class: 'toolbar' }, status.enabled ? [
      button('Kurtarma kodlarını yenile', { onClick: () => factorDialog('recovery') }),
      button('Kapat', { onClick: () => factorDialog('disable') })
    ] : button('İki adımlı girişi kur', { onClick: () => factorDialog('setup') })));
}

export function enrollmentPage(root) {
  root.replaceChildren(h('main', { class: 'login-page' }, h('div', { class: 'login-card' },
    h('h1', { text: 'İki adımlı giriş gerekli' }),
    h('p', { text: 'Kurumunuz bu rol için ek doğrulama istiyor. Dashboard ve raporlara erişmeden önce kurulumu tamamlayın. Bu kurulum oturumu 10 dakika geçerlidir.' }),
    button('İki adımlı girişi kur', { variant: 'primary', onClick: () => factorDialog('setup') }),
    button('Çıkış yap', { onClick: async () => { try { await post('/api/logout'); } finally { setCsrf(''); location.reload(); } } }))));
}
