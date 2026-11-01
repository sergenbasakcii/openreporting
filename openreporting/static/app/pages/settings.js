// System settings: SMTP, LDAP, security policy, limits and source policy edited in the browser.
// Values override the server environment file; secrets are write-only and never shown again.
import { h, button, input, textarea, select, field, toggle, tabs, toast, modal, confirmDialog, fmtDateTime, loading, clear } from '../dom.js';
import { icon } from '../icons.js';
import { get, post, put } from '../api.js';
import { setBreadcrumbs } from '../router.js';

const ROLE_LABELS = { admin: 'Yönetici', editor: 'Editör', viewer: 'İzleyici' };

// [field, control, label, hint]
const SCOPES = {
  mail: { label: 'E-posta (SMTP)', icon: 'mail', test: true,
    intro: 'Zamanlanmış raporların e-postayla gönderimi. Sertifika ve sunucu adı her zaman doğrulanır; şifresiz bağlantı yoktur.',
    fields: [
      ['mail_enabled', 'toggle', 'E-posta gönderimi açık'],
      ['smtp_host', 'text', 'SMTP sunucusu', 'Örn. smtp.example.com'],
      ['smtp_port', 'number', 'Port', 'STARTTLS için genellikle 587, doğrudan TLS için 465'],
      ['smtp_security', 'choice', 'Bağlantı güvenliği', '', [{ value: 'starttls', label: 'STARTTLS (587)' }, { value: 'tls', label: 'Doğrudan TLS (465)' }]],
      ['smtp_user', 'text', 'Kullanıcı adı', 'Kimlik doğrulamasız kurum relay sunucusu için boş bırakın'],
      ['smtp_password', 'secret', 'Parola'],
      ['smtp_from', 'text', 'Gönderen adresi', 'Örn. raporlar@example.com'],
      ['recipient_domains', 'list', 'İzinli alıcı alan adları', 'Virgülle ayırın: example.com, example.org — başka alan adına gönderilmez'],
      ['smtp_timeout', 'number', 'Zaman aşımı (saniye)', '1–120'],
      ['smtp_local_hostname', 'text', 'EHLO adı (isteğe bağlı)', 'Relay sunucusu belirli bir ad istiyorsa'],
      ['smtp_ca_pem', 'pem', 'Kurum CA sertifikası (isteğe bağlı)', 'Kurumunuz kendi sertifika otoritesini kullanıyorsa PEM metnini yapıştırın'],
    ] },
  ldap: { label: 'LDAP / Active Directory', icon: 'users', test: true,
    intro: 'Kullanıcılar kurum dizin parolasıyla giriş yapar; rol, dizin grubuna göre verilir. En az bir yerel yönetici hesabını her zaman koruyun.',
    fields: [
      ['ldap_enabled', 'toggle', 'LDAP ile giriş açık'],
      ['ldap_url', 'text', 'Sunucu adresi', 'ldaps://dc.example.com:636 veya ldap://dc.example.com:389 (StartTLS zorunlu)'],
      ['ldap_bind_dn', 'text', 'Servis hesabı (bind DN)', 'Örn. CN=svc-openreporting,OU=Service,DC=example,DC=com'],
      ['ldap_bind_password', 'secret', 'Servis hesabı parolası'],
      ['ldap_base_dn', 'text', 'Arama tabanı (base DN)', 'Örn. DC=example,DC=com'],
      ['ldap_user_filter', 'text', 'Kullanıcı filtresi', '{username} tam bir kez geçmeli'],
      ['ldap_id_attribute', 'text', 'Kimlik özniteliği', 'Active Directory: objectGUID'],
      ['ldap_group_attribute', 'text', 'Grup özniteliği', 'Active Directory: memberOf'],
      ['ldap_group_roles', 'grouproles', 'Grup → rol eşlemesi', 'Doğrudan grup DN’i; birden fazla eşleşmede en yüksek rol geçerlidir. Eşleşme yoksa giriş yok.'],
      ['ldap_timeout', 'number', 'Zaman aşımı (saniye)', '1–60'],
      ['ldap_session_minutes', 'number', 'LDAP oturum süresi (dakika)', '5–240'],
      ['ldap_ca_pem', 'pem', 'Kurum CA sertifikası (isteğe bağlı)', 'PEM metnini yapıştırın'],
    ] },
  security: { label: 'Güvenlik', icon: 'shield',
    intro: 'İki adımlı giriş politikası açık oturumlara da birkaç saniye içinde uygulanır; yeni oturum süresi sonraki girişlerde geçerli olur.',
    fields: [
      ['session_hours', 'number', 'Oturum süresi (saat)', '1–168'],
      ['mfa_required_roles', 'roles', 'İki adımlı giriş zorunlu roller', 'Seçilen rollerdeki kullanıcılar ilk girişte doğrulayıcı uygulama kurar'],
    ] },
  limits: { label: 'Sorgu ve rapor sınırları', icon: 'activity',
    intro: 'Sunucu belleğini ve kaynak sistemleri koruyan sınırlar. Değerleri yükseltmek bellek kullanımını artırır.',
    fields: [
      ['query_timeout_ms', 'number', 'SQL sorgu zaman aşımı (ms)', '1000–300000'],
      ['max_rows', 'number', 'En fazla satır', '1–1.000.000'],
      ['query_concurrency', 'number', 'Panel başına paralel sorgu', '1–64'],
      ['max_series_points', 'number', 'Yanıt başına nokta bütçesi', '10.000–50.000.000; aşılırsa sorgu reddedilir'],
      ['report_retention_days', 'number', 'Rapor arşivi saklama (gün)', '0 = sınırsız'],
    ] },
  sources: { label: 'Veri kaynağı politikası', icon: 'database',
    intro: 'Veri kaynaklarının hangi adreslere bağlanabileceği. Varsayılan kapalı değerler en güvenlisidir.',
    fields: [
      ['allow_http_datasources', 'toggle', 'Şifresiz HTTP kaynaklarına izin ver', 'Önerilmez: kimlik bilgileri ağda açık gider'],
      ['allow_loopback_datasources', 'toggle', 'Sunucunun kendi yerel servislerine izin ver', 'Yalnız aynı sunucudaki Prometheus/Loki gibi servisler için açın'],
    ] },
};
const TAB_ORDER = ['mail', 'ldap', 'security', 'limits', 'sources', 'server'];

function sourceBadge(meta) {
  const ui = meta.source === 'ui';
  return h('span', { class: `badge ${ui ? 'info' : ''}`, title: ui ? 'Bu değer arayüzden kaydedildi' : `Sunucu dosyasından: ${meta.env || '—'}`,
    text: ui ? 'Arayüz' : 'Sunucu dosyası' });
}

function askPassword(title, okText) {
  return new Promise((resolve) => {
    let value = '';
    let done = false;
    const pw = input({ type: 'password', autocomplete: 'current-password', onInput: (e) => { value = e.target.value; },
      onKeydown: (e) => { if (e.key === 'Enter' && value) { done = true; dlg.close(); resolve(value); } } });
    const dlg = modal({ title, body: field('Mevcut parolanız', pw, 'Ayar değişiklikleri parolanızla onaylanır ve denetim kaydına yazılır.'),
      onClose: () => { if (!done) resolve(null); },
      footer: [button('Vazgeç', { onClick: () => dlg.close() }), button(okText, { variant: 'primary', onClick: () => { if (!value) return; done = true; dlg.close(); resolve(value); } })] });
    setTimeout(() => pw.focus(), 0);
  });
}

function control(spec, meta, draft) {
  const [name, kind, label, hint, options] = spec;
  const set = (value) => { draft.values[name] = value; draft.changed(); };
  const current = meta.value;
  if (kind === 'toggle') return h('div', { class: 'field' }, toggle(label, Boolean(current), (v) => set(v)), hint ? h('div', { class: 'hint', text: hint }) : null);
  if (kind === 'number') return field(label, input({ type: 'number', value: current, onInput: (e) => set(e.target.value === '' ? null : Number(e.target.value)) }), hint);
  if (kind === 'choice') return field(label, select(options, current, (v) => set(v)), hint);
  if (kind === 'list') return field(label, input({ value: (current || []).join(', '), onInput: (e) => set(e.target.value.split(',').map((x) => x.trim()).filter(Boolean)) }), hint);
  if (kind === 'pem') return field(label, textarea({ rows: 4, value: current || '', placeholder: '-----BEGIN CERTIFICATE-----', onInput: (e) => set(e.target.value) }), hint);
  if (kind === 'roles') {
    const chosen = new Set(current || []);
    return h('div', { class: 'field' }, h('label', { text: label }),
      h('div', { class: 'toolbar' }, Object.entries(ROLE_LABELS).map(([role, text]) => toggle(text, chosen.has(role), (on) => {
        if (on) chosen.add(role); else chosen.delete(role);
        set(Object.keys(ROLE_LABELS).filter((r) => chosen.has(r)));
      }))), hint ? h('div', { class: 'hint', text: hint }) : null);
  }
  if (kind === 'grouproles') return groupRoles(label, hint, current || {}, set);
  if (kind === 'secret') {
    const status = h('span', { class: `badge ${meta.set ? 'ok' : ''}`, text: meta.set ? 'Kayıtlı' : 'Ayarlı değil' });
    const box = input({ type: 'password', autocomplete: 'new-password', placeholder: meta.set ? 'Değiştirmek için yeni değeri yazın' : '',
      onInput: (e) => { draft.secrets[name] = e.target.value || null; draft.changed(); } });
    const clearIt = meta.set ? toggle('Kaldır', false, (on) => { draft.secrets[name] = on ? '' : null; box.disabled = on; draft.changed(); }) : null;
    return h('div', { class: 'field' }, h('label', { text: label }), h('div', { class: 'toolbar' }, box, status, clearIt),
      h('div', { class: 'hint', text: 'Kayıtlı parola güvenlik nedeniyle gösterilmez; boş bırakırsanız mevcut değer korunur.' }));
  }
  return field(label, input({ value: current ?? '', onInput: (e) => set(e.target.value) }), hint);
}

function groupRoles(label, hint, initial, set) {
  const rows = Object.entries(initial).map(([dn, role]) => ({ dn, role }));
  const host = h('div');
  const emit = () => set(Object.fromEntries(rows.filter((r) => r.dn.trim()).map((r) => [r.dn.trim(), r.role])));
  const draw = () => {
    clear(host);
    rows.forEach((row, index) => host.append(h('div', { class: 'toolbar', style: { marginBottom: '6px' } },
      h('div', { style: { flex: '1', minWidth: '240px' } }, input({ value: row.dn, label: `Grup DN ${index + 1}`, placeholder: 'CN=ReportReaders,OU=Groups,DC=example,DC=com', onInput: (e) => { row.dn = e.target.value; emit(); } })),
      select(Object.entries(ROLE_LABELS).map(([value, text]) => ({ value, label: text })), row.role, (v) => { row.role = v; emit(); }, { label: `Grup ${index + 1} rolü` }),
      button('', { icon: 'trash', title: 'Eşlemeyi kaldır', size: 'sm', onClick: () => { rows.splice(index, 1); emit(); draw(); } }))));
    host.append(button('Grup ekle', { icon: 'plus', size: 'sm', onClick: () => { rows.push({ dn: '', role: 'viewer' }); draw(); } }));
  };
  draw();
  return h('div', { class: 'field', role: 'group', 'aria-label': label }, h('label', { text: label }), host, hint ? h('div', { class: 'hint', text: hint }) : null);
}

function scopePanel(scope, data, reload) {
  const def = SCOPES[scope];
  const draft = { values: {}, secrets: {}, changed: () => { save.disabled = !dirty(); } };
  const dirty = () => Object.keys(draft.values).length > 0 || Object.values(draft.secrets).some((v) => v !== null && v !== undefined);
  const pendingSecrets = () => Object.fromEntries(Object.entries(draft.secrets).filter(([, v]) => v !== null && v !== undefined));
  const save = button('Kaydet', { variant: 'primary', icon: 'save', disabled: true, onClick: async () => {
    const password = await askPassword(`${def.label} · değişiklikleri kaydet`, 'Kaydet');
    if (!password) return;
    try {
      await put(`/api/admin/settings/${scope}`, { revision: data.revision, values: draft.values, secrets: pendingSecrets(), password });
      toast('Kaydedildi. Birkaç saniye içinde tüm servislerde geçerli olur.', 'ok');
      reload(scope);
    } catch (err) { toast(err.message, 'error'); }
  } });
  const anyUi = Object.values(data.fields).some((meta) => meta.source === 'ui');
  const actions = h('div', { class: 'toolbar', style: { marginTop: '12px' } }, save,
    def.test ? button('Bağlantıyı test et', { icon: 'activity', onClick: async (e) => {
      const trigger = e.currentTarget;
      const values = Object.fromEntries(Object.entries(data.fields).filter(([name, meta]) => !('set' in meta) && name !== `${scope === 'mail' ? 'mail' : 'ldap'}_enabled`).map(([name, meta]) => [name, meta.value]));
      trigger.disabled = true;
      try {
        const result = await post(`/api/admin/settings/${scope}/test`, { values: { ...values, ...draft.values }, secrets: pendingSecrets() });
        toast(result.message, result.ok ? 'ok' : 'error', 8000);
      } catch (err) { toast(err.message, 'error', 8000); } finally { trigger.disabled = false; }
    } }) : null,
    anyUi ? button('Sunucu dosyasındaki değerlere dön', { onClick: async () => {
      if (!(await confirmDialog('Sunucu değerlerine dön', `${def.label} bölümünde arayüzden kaydedilen tüm değerler silinir; sunucu dosyasındaki değerler geçerli olur.`, { okText: 'Devam' }))) return;
      const password = await askPassword(`${def.label} · sunucu değerlerine dön`, 'Geri dön');
      if (!password) return;
      try { await post(`/api/admin/settings/${scope}/reset`, { revision: data.revision, password }); toast('Sunucu dosyasındaki değerler geçerli', 'ok'); reload(scope); } catch (err) { toast(err.message, 'error'); }
    } }) : null);
  const rows = def.fields.map((spec) => {
    const meta = data.fields[spec[0]];
    return h('div', { class: 'setting-row' }, h('div', { class: 'grow' }, control(spec, meta, draft)), sourceBadge(meta));
  });
  return h('div', { class: 'card' },
    h('h2', { class: 'section-heading' }, icon(def.icon), ` ${def.label}`),
    h('p', { class: 'muted', text: def.intro }),
    data.error ? h('div', { class: 'alert error', role: 'alert', text: `Kayıtlı ayar kullanılamıyor: ${data.error}` }) : null,
    data.updated_at ? h('p', { class: 'hint', text: `Son değişiklik: ${data.updated_by || '—'} · ${fmtDateTime(data.updated_at)}` }) : null,
    ...rows, actions);
}

function serverPanel(view) {
  return h('div', { class: 'card' },
    h('h2', { class: 'section-heading' }, icon('lock'), ' Sunucu (salt okunur)'),
    h('p', { class: 'muted', text: `Bu değerler servisler başlarken okunur. Değiştirmek için sunucuda ${view.env_file} dosyasını düzenleyip servisleri yeniden başlatın.` }),
    h('table', { class: 'list' }, h('tr', ['Ayar', 'Değer', 'Sunucu dosyasındaki ad'].map((t) => h('th', { text: t }))),
      view.server.map((row) => h('tr', h('td', { text: row.label }), h('td', { class: 'mono', text: row.value }), h('td', { class: 'mono faint', text: row.env })))),
    h('pre', { class: 'mono hint', text: view.restart }));
}

export async function settingsPage(root) {
  setBreadcrumbs([{ label: 'Yönetim' }, { label: 'Sistem ayarları' }]);
  const page = h('div', { class: 'page' });
  root.append(page);
  const body = h('div');
  let active = new URLSearchParams(location.search).get('tab');
  if (!TAB_ORDER.includes(active)) active = 'mail';
  page.append(h('div', { class: 'page-header' }, h('div', h('h1', icon('settings'), 'Sistem ayarları'),
    h('p', { class: 'sub', text: 'Buradan kaydedilen değerler sunucu dosyasındakilerin önüne geçer ve servisleri yeniden başlatmadan birkaç saniye içinde geçerli olur.' }))));
  const items = TAB_ORDER.map((id) => ({ id, label: id === 'server' ? 'Sunucu' : SCOPES[id].label }));
  let view = null;
  const render = () => {
    clear(body);
    body.append(active === 'server' ? serverPanel(view) : scopePanel(active, view.scopes[active], load));
  };
  async function load(keep) {
    if (keep) active = keep;
    clear(body).append(loading());
    try { view = await get('/api/admin/settings'); render(); } catch (err) { clear(body).append(h('div', { class: 'alert error', role: 'alert', text: err.message })); }
  }
  page.append(tabs(items, active, (id) => {
    active = id;
    history.replaceState(null, '', `${location.pathname}?tab=${id}`);
    if (view) render();
  }), body);
  await load();
}
