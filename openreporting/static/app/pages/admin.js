// Administration: users, server status, audit log; self-service profile.
import { h, button, input, select, field, toggle, toast, modal, confirmDialog, fmtDateTime, timeAgo, loading, clear } from '../dom.js';
import { icon } from '../icons.js';
import { get, post, put, patch } from '../api.js';
import { setBreadcrumbs } from '../router.js';
import { THEMES, SYSTEM, normalisePreference, resolveTheme, themeSwatch } from '../themes.js';

const ROLE_LABELS = { admin: 'Yönetici', editor: 'Editör', viewer: 'İzleyici' };
const roleOptions = Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }));

function bytes(n) { if (!Number.isFinite(n)) return '—'; const u = ['B', 'KiB', 'MiB', 'GiB', 'TiB']; let i = 0; while (n >= 1024 && i < u.length - 1) { n /= 1024; i += 1; } return `${n.toFixed(1)} ${u[i]}`; }

export async function usersPage(root, { app }) {
  setBreadcrumbs([{ label: 'Yönetim' }, { label: 'Kullanıcılar' }]);
  const page = h('div', { class: 'page' });
  root.append(page);
  const draw = async () => {
    const users = await get('/api/users');
    clear(page);
    page.append(h('div', { class: 'page-header' }, h('div', h('h1', icon('users'), 'Kullanıcılar'), h('p', { class: 'sub', text: 'Roller: Yönetici (her şey), Editör (dashboard, rapor, Keşfet), İzleyici (kayıtlı dashboard ve raporları görüntüleme).' })),
      button('Kullanıcı ekle', { icon: 'plus', variant: 'primary', onClick: () => addUser(draw) })));
    const table = h('table', { class: 'list' }, h('tr', ['Kullanıcı', 'Ad', 'E-posta', 'Rol', 'Durum', 'Son giriş', 'İşlemler'].map((t) => h('th', { text: t }))));
    for (const u of users) {
      table.append(h('tr', h('td', h('b', { text: u.username }), u.auth_provider === 'ldap' ? h('span', { class: 'badge', text: 'LDAP' }) : null, u.mfa_enabled ? h('span', { class: 'badge ok', title: 'İki adımlı giriş etkin', text: '2FA' }) : null), h('td', { text: u.display_name || '—' }), h('td', { text: u.email || '—' }),
        h('td', u.auth_provider === 'ldap' ? h('span', { text: `${ROLE_LABELS[u.role]} · dizin grubu` }) : select(roleOptions, u.role, async (v) => { try { await patch(`/api/users/${u.id}`, { role: v }); toast('Rol güncellendi', 'ok'); } catch (err) { toast(err.message, 'error'); draw(); } }, { label: `${u.username} kullanıcısının rolü` })),
        h('td', u.active ? h('span', { class: 'badge ok', text: 'etkin' }) : h('span', { class: 'badge err', text: 'devre dışı' })),
        h('td', { text: u.last_login_at ? timeAgo(u.last_login_at) : 'hiç' }),
        h('td', { class: 'actions' },
          button('Düzenle', { size: 'sm', onClick: () => editUser(u, draw) }),
          u.auth_provider === 'ldap' ? null : button('Parola sıfırla', { size: 'sm', onClick: () => resetPassword(u) }),
          u.mfa_enabled && u.id !== app.user.id ? button('İki adımlı girişi sıfırla', { size: 'sm', onClick: () => resetFactor(u, draw) }) : null,
          u.id !== app.user.id ? button(u.active ? 'Devre dışı bırak' : 'Etkinleştir', { size: 'sm', onClick: async () => {
            if (u.active && !(await confirmDialog('Kullanıcıyı devre dışı bırak', `${u.username} oturumları sonlandırılacak.`, { danger: true, okText: 'Devre dışı bırak' }))) return;
            try { await patch(`/api/users/${u.id}`, { active: !u.active }); draw(); } catch (err) { toast(err.message, 'error'); }
          } }) : null)));
    }
    page.append(h('div', { class: 'card' }, table));
  };
  await draw();
}

function addUser(done) {
  const m = { username: '', password: '', role: 'viewer', email: '', display_name: '' };
  const dlg = modal({ title: 'Yeni kullanıcı', body: h('div', { class: 'form-grid' },
    field('Kullanıcı adı', input({ onChange: (e) => { m.username = e.target.value; } })), field('Ad soyad', input({ onChange: (e) => { m.display_name = e.target.value; } })),
    field('E-posta', input({ type: 'email', onChange: (e) => { m.email = e.target.value; } })), field('Rol', select(roleOptions, 'viewer', (v) => { m.role = v; })),
    field('Parola (en az 14 karakter)', input({ type: 'password', autocomplete: 'new-password', onChange: (e) => { m.password = e.target.value; } }))),
  footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Oluştur', { variant: 'primary', onClick: async () => {
    try { await post('/api/users', m); toast('Kullanıcı oluşturuldu', 'ok'); dlg.close(); done(); } catch (err) { toast(err.message, 'error'); }
  } })] });
}

function editUser(u, done) {
  const m = { email: u.email || '', display_name: u.display_name || '' };
  const dlg = modal({ title: `Düzenle · ${u.username}`, body: h('div', field('Ad soyad', input({ value: m.display_name, onChange: (e) => { m.display_name = e.target.value; } })),
    field('E-posta', input({ value: m.email, onChange: (e) => { m.email = e.target.value; } }))),
  footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Kaydet', { variant: 'primary', onClick: async () => {
    try { await patch(`/api/users/${u.id}`, m); dlg.close(); done(); } catch (err) { toast(err.message, 'error'); }
  } })] });
}

const RESET_REASONS = [{ value: 'lost-device', label: 'Telefon kayboldu / değişti' }, { value: 'compromise', label: 'Kurulum anahtarı başkasına göründü' }, { value: 'recovery', label: 'Diğer kurtarma' }];

function resetFactor(u, done) {
  const m = { reason: 'lost-device', password: '' };
  const dlg = modal({ title: `İki adımlı girişi sıfırla · ${u.username}`, body: h('div',
    h('p', { class: 'muted', text: 'Kullanıcının doğrulayıcı kaydı ve kurtarma kodları silinir, açık oturumları kapanır. Parolası değişmez; sonraki girişte QR ile yeniden kurar.' }),
    field('Neden', select(RESET_REASONS, m.reason, (v) => { m.reason = v; })),
    field('Sizin mevcut parolanız', input({ type: 'password', autocomplete: 'current-password', onInput: (e) => { m.password = e.target.value; } }))),
  footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Sıfırla', { variant: 'danger', onClick: async () => {
    try { await post(`/api/users/${u.id}/mfa/reset`, m); toast('İki adımlı giriş sıfırlandı', 'ok'); dlg.close(); done(); } catch (err) { toast(err.message, 'error'); }
  } })] });
}

function resetPassword(u) {
  let password = '';
  const dlg = modal({ title: `Parola sıfırla · ${u.username}`, body: [field('Yeni parola (en az 14 karakter)', input({ type: 'password', autocomplete: 'new-password', onChange: (e) => { password = e.target.value; } })),
    h('p', { class: 'hint', text: 'Kullanıcının tüm oturumları sonlandırılır.' })],
  footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Sıfırla', { variant: 'primary', onClick: async () => {
    try { await post(`/api/users/${u.id}/password`, { password }); toast('Parola sıfırlandı', 'ok'); dlg.close(); } catch (err) { toast(err.message, 'error'); }
  } })] });
}

export async function serverPage(root) {
  setBreadcrumbs([{ label: 'Yönetim' }, { label: 'Sunucu durumu' }]);
  const page = h('div', { class: 'page' }, loading());
  root.append(page);
  const draw = async () => {
    const [s, integrations] = await Promise.all([get('/api/admin/stats'), get('/api/admin/integrations').catch(() => null)]);
    clear(page);
    const worker = s.worker || {};
    const used = s.disk.total_bytes - s.disk.free_bytes;
    page.append(h('div', { class: 'page-header' }, h('div', h('h1', icon('activity'), 'Sunucu durumu'), h('p', { class: 'sub', text: `OpenReporting v${s.version} · Python ${s.python} · ${s.platform}` })),
      button('Yenile', { icon: 'refresh', onClick: draw })),
    h('div', { class: 'stat-cards' }, Object.entries({ Kullanıcı: s.counts.users, Dashboard: s.counts.dashboards, Klasör: s.counts.folders, 'Veri kaynağı': s.counts.datasources,
      Rapor: s.counts.reports, 'Etkin zamanlama': s.activeSchedules, 'Rapor çalıştırması': s.counts.runs }).map(([k, v]) => h('div', { class: 'stat-card' }, h('span', { text: k }), h('b', { text: v })))),
    h('div', { class: 'split-2' },
      h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Rapor işçisi (worker)' }),
        h('p', {}, worker.state === 'up' ? h('span', { class: 'badge ok', text: 'çalışıyor' }) : worker.state === 'stale' ? h('span', { class: 'badge warn', text: 'yanıt vermiyor' }) : h('span', { class: 'badge err', text: 'başlatılmadı' })),
        h('p', { class: 'muted', text: worker.last_tick ? `Son sinyal: ${fmtDateTime(worker.last_tick)} (${worker.heartbeat_age_seconds} sn önce) · döngü: ${worker.tick_count}` : 'Worker servisi henüz çalışmadı. Ubuntu’da: systemctl status openreporting-worker' }),
        worker.last_error ? h('div', { class: 'alert error', text: worker.last_error }) : null,
        h('h3', { class: 'subsection-heading', text: 'Çalıştırma durumları' }), h('div', { class: 'chips' }, s.runStatus.map((r) => h('span', { class: 'chip', text: `${r.status}: ${r.count}` })))),
      h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Depolama ve bütünlük' }),
        h('p', { text: `Veri diski: ${bytes(used)} / ${bytes(s.disk.total_bytes)} kullanılıyor (${bytes(s.disk.free_bytes)} boş)` }),
        h('div', { class: 'progress' }, h('i', { style: { width: `${Math.round((used / s.disk.total_bytes) * 100)}%` } })),
        h('p', { style: { marginTop: '10px' }, text: `Rapor arşivi: ${bytes(s.disk.archive_bytes)}` }),
        h('p', {}, 'Denetim zinciri: ', s.auditChainValid ? h('span', { class: 'badge ok', text: 'geçerli' }) : h('span', { class: 'badge err', text: `bozuk (#${s.auditBrokenId})` })),
        h('p', {}, 'E-posta gönderimi: ', s.mailEnabled ? h('span', { class: 'badge ok', text: 'etkin' }) : h('span', { class: 'badge', text: 'kapalı (Sistem ayarları → E-posta)' })))),
      h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Kurumsal bağlantılar' }),
        h('p', { class: 'hint', text: 'Bağlantı testleri e-posta göndermez. Ayarlar sunucuda güvenli yapılandırma dosyasıyla yönetilir.' }),
        integrations ? null : h('p', { class: 'muted', text: 'Bağlantı durumu alınamadı.' }),
        ...(integrations ? [['ldap', 'LDAP / Active Directory'], ['smtp', 'SMTP']] : []).map(([kind, label]) => h('div', { class: 'toolbar', style: { marginBottom: '8px' } },
          h('span', { text: label }), h('span', { class: 'badge', text: integrations[kind].enabled ? 'etkin' : 'kapalı' }),
          button('Bağlantıyı kontrol et', { size: 'sm', disabled: !integrations[kind].enabled, onClick: async (e) => {
            const control = e.currentTarget;
            control.disabled = true;
            try { const result = await post(`/api/admin/integrations/${kind}/check`, {}); toast(result.message, result.ok ? 'ok' : 'error'); }
            catch (err) { toast(err.message, 'error'); }
            finally { if (control.isConnected) control.disabled = false; }
          } })))));
  };
  await draw();
}

export async function auditPage(root) {
  setBreadcrumbs([{ label: 'Yönetim' }, { label: 'Denetim kaydı' }]);
  const page = h('div', { class: 'page' });
  root.append(page);
  let offset = 0;
  let action = '';
  const tableHost = h('div', { class: 'card' });
  let drawSeq = 0;
  const draw = async () => {
    const seq = ++drawSeq;
    const rows = await get(`/api/audit?limit=200&offset=${offset}&action=${encodeURIComponent(action)}`);
    if (seq !== drawSeq) return;  // a newer page request won
    clear(tableHost);
    const table = h('table', { class: 'list' }, h('tr', ['#', 'Zaman', 'Kullanıcı', 'İşlem', 'Nesne', 'Ayrıntı'].map((t) => h('th', { text: t }))));
    for (const r of rows) table.append(h('tr', h('td', { text: r.id }), h('td', { class: 'nowrap', text: fmtDateTime(r.happened_at) }), h('td', { class: 'mono', text: r.actor.slice(0, 13) }),
      h('td', h('span', { class: 'badge', text: r.action })), h('td', { class: 'mono', text: `${r.object_type}/${r.object_id.slice(0, 13)}` }), h('td', { class: 'mono faint', text: r.details === '{}' ? '' : r.details.slice(0, 160) })));
    tableHost.append(table, h('div', { class: 'toolbar', style: { marginTop: '10px' } },
      button('Önceki', { disabled: offset === 0, onClick: () => { offset = Math.max(0, offset - 200); draw(); } }), button('Sonraki', { disabled: rows.length < 200, onClick: () => { offset += 200; draw(); } })));
  };
  page.append(h('div', { class: 'page-header' }, h('div', h('h1', icon('shield'), 'Denetim kaydı'), h('p', { class: 'sub', text: 'Tüm değişiklikler SHA-256 hash zinciriyle kayıt altındadır.' })),
    h('div', { style: { width: '280px' } }, input({ label: 'İşlem filtresi', placeholder: 'İşlem filtresi (ör. dashboard.)', onKeydown: (e) => { if (e.key === 'Enter') { action = e.target.value; offset = 0; draw(); } } }))), tableHost);
  await draw();
}

// Radio group of theme cards (arrow keys move between options, like native radios).
function themePicker(current, onPick) {
  const options = [...THEMES.map((t) => ({ ...t, value: t.id })),
    { value: SYSTEM, name: 'Sistem', description: 'İşletim sisteminin açık/koyu ayarına göre Aurora veya Porselen.', swatch: [...resolveTheme('aurora').swatch.slice(0, 2), ...resolveTheme('porcelain').swatch.slice(0, 2)] }];
  let selected = current;
  const cards = options.map((t) => h('button', { type: 'button', class: 'theme-option', role: 'radio', 'aria-checked': String(t.value === selected), tabindex: t.value === selected ? '0' : '-1',
    onClick: () => pick(t.value) }, themeSwatch(t, h), h('b', { text: t.name }), h('span', { class: 'hint', text: t.description })));
  function pick(value) {
    selected = value;
    cards.forEach((card, i) => { const on = options[i].value === value; card.setAttribute('aria-checked', String(on)); card.tabIndex = on ? 0 : -1; });
    onPick(value);
  }
  const group = h('div', { class: 'theme-grid', role: 'radiogroup', 'aria-label': 'Tema', onKeydown: (e) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!step) return;
    e.preventDefault();
    const next = (options.findIndex((t) => t.value === selected) + step + options.length) % options.length;
    pick(options[next].value);
    cards[next].focus();
  } }, cards);
  return h('div', { class: 'field' }, h('span', { class: 'field-label', text: 'Tema' }), group);
}

export async function profilePage(root, { app, applyTheme }) {
  setBreadcrumbs([{ label: 'Profil' }]);
  const me = await get('/api/user');
  const dashboards = await get('/api/search').catch(() => []);
  const { mfaCard } = await import('../mfa.js');
  const factorCard = await mfaCard();
  const prefs = { ...me.preferences };
  const pw = { old_password: '', new_password: '', confirm: '' };
  root.append(h('div', { class: 'page' }, h('div', { class: 'page-header' }, h('div', h('h1', icon('user'), me.display_name || me.username), h('p', { class: 'sub', text: `${ROLE_LABELS[me.role] || me.role} · son giriş ${fmtDateTime(me.last_login_at)}` }))),
    h('div', { class: 'split-2' },
      h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Tercihler' }),
        themePicker(normalisePreference(prefs.theme), (v) => { prefs.theme = v; applyTheme(v); }),
        field('Saat dilimi', select([{ value: 'browser', label: 'Tarayıcı' }, { value: 'utc', label: 'UTC' }, { value: 'Europe/Istanbul', label: 'Europe/Istanbul' }], prefs.timezone || 'browser', (v) => { prefs.timezone = v; })),
        field('Ana sayfa dashboard’u', select([{ value: '', label: 'Varsayılan ana sayfa' }, ...dashboards.map((d) => ({ value: d.uid, label: d.title }))], prefs.home_dashboard_uid || '', (v) => { prefs.home_dashboard_uid = v || null; })),
        h('div', { class: 'field' }, toggle('Raporlarım başarısız olunca veya zamanlaması kapanınca e-posta al', prefs.notify_report_failures !== false, (on) => { prefs.notify_report_failures = on; }),
          h('div', { class: 'hint', text: me.email ? `Bildirimler ${me.email} adresine gider.` : 'E-posta adresiniz tanımlı değil; yöneticiniz Kullanıcılar sayfasından ekleyebilir.' })),
        button('Tercihleri kaydet', { variant: 'primary', onClick: async () => { try { await put('/api/user/preferences', prefs); app.prefs = prefs; toast('Kaydedildi', 'ok'); } catch (err) { toast(err.message, 'error'); } } })),
      me.auth_provider === 'ldap' ? h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Dizin hesabı' }), h('p', { text: 'Parolanız ve rolünüz kurumunuzun dizin hizmetinde yönetilir.' })) : h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Parola değiştir' }),
        field('Mevcut parola', input({ type: 'password', autocomplete: 'current-password', onChange: (e) => { pw.old_password = e.target.value; } })),
        field('Yeni parola (en az 14 karakter)', input({ type: 'password', autocomplete: 'new-password', onChange: (e) => { pw.new_password = e.target.value; } })),
        field('Yeni parola (tekrar)', input({ type: 'password', autocomplete: 'new-password', onChange: (e) => { pw.confirm = e.target.value; } })),
        button('Parolayı değiştir', { onClick: async () => {
          if (pw.new_password !== pw.confirm) { toast('Yeni parolalar eşleşmiyor', 'error'); return; }
          try { await put('/api/user/password', { old_password: pw.old_password, new_password: pw.new_password }); toast('Parola değiştirildi; diğer oturumlar kapatıldı', 'ok'); } catch (err) { toast(err.message, 'error'); }
        } }))), factorCard));
}

export { toggle };
