// Command palette (Ctrl+K / ⌘K): jump to any dashboard, smart dashboard, page or action by typing.
// Results are fuzzy-ranked; ↑/↓ move, Enter opens, Esc closes. Dashboards come from /api/search,
// so permissions are applied by the server exactly as in the lists.
import { h, clear } from './dom.js';
import { icon } from './icons.js';
import { get } from './api.js';
import { navigate } from './router.js';
import { score } from './fuzzy.js';

let open = null;

function staticEntries(app) {
  const admin = app.user.role === 'admin'; const editor = ['admin', 'editor'].includes(app.user.role);
  const page = (label, path, iconName, kind = 'Sayfa') => ({ label, kind, icon: iconName, run: () => navigate(path) });
  return [
    page('Ana sayfa', '/', 'home'), page('Dashboard’lar', '/dashboards', 'apps'), page('Akıllı dashboard', '/smart', 'report'),
    page('Raporlar', '/reports', 'report'), editor && page('Keşfet', '/explore', 'compass'),
    editor && { label: 'Yeni dashboard', kind: 'İşlem', icon: 'plus', run: () => navigate('/dashboards/new') },
    editor && { label: 'Yeni akıllı dashboard (boş sayfa)', kind: 'İşlem', icon: 'plus', run: () => navigate('/smart/new') },
    editor && { label: 'Şablondan akıllı dashboard: Yönetici özeti', kind: 'İşlem', icon: 'plus', run: () => navigate('/smart/new?template=executive') },
    editor && { label: 'Şablondan akıllı dashboard: Host sağlık raporu', kind: 'İşlem', icon: 'plus', run: () => navigate('/smart/new?template=host-health') },
    editor && { label: 'Yeni rapor zamanla', kind: 'İşlem', icon: 'calendar', run: () => navigate('/reports/new') },
    admin && page('Veri kaynakları', '/datasources', 'database', 'Yönetim'), admin && page('Kullanıcılar', '/admin/users', 'user', 'Yönetim'),
    admin && page('Takımlar', '/admin/teams', 'users', 'Yönetim'), admin && page('Sistem ayarları', '/admin/settings', 'settings', 'Yönetim'),
    admin && page('API', '/admin/api', 'code', 'Yönetim'), admin && page('Eklentiler', '/admin/plugins', 'layers', 'Yönetim'),
    admin && page('Sunucu durumu', '/admin/server', 'activity', 'Yönetim'), admin && page('Denetim kaydı', '/admin/audit', 'shield', 'Yönetim'),
    page('Profil ve tercihler (tema)', '/profile', 'user'),
  ].filter(Boolean);
}

export function openPalette(app) {
  if (open) { open.focus(); return; }
  const opener = document.activeElement;
  const field = h('input', { class: 'palette-input', placeholder: 'Dashboard, sayfa veya işlem ara…', 'aria-label': 'Komut paleti', autocomplete: 'off', spellcheck: 'false',
    role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'palette-list' });
  const list = h('div', { class: 'palette-list', id: 'palette-list', role: 'listbox' });
  const hint = h('div', { class: 'palette-hint' }, h('span', { text: '↑↓ seç · Enter aç · Esc kapat' }), h('span', { text: 'Ctrl+K' }));
  const box = h('div', { class: 'palette', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Komut paleti' }, h('div', { class: 'palette-search' }, icon('search'), field), list, hint);
  const backdrop = h('div', { class: 'palette-backdrop', onMousedown: (e) => { if (e.target === backdrop) close(); } }, box);
  let entries = staticEntries(app); let shown = []; let active = 0;
  const close = () => { backdrop.remove(); open = null; document.removeEventListener('keydown', onKey, true); if (opener && opener.focus) opener.focus(); };
  const choose = (entry) => { close(); entry.run(); };
  function draw() {
    const q = field.value.trim();
    shown = entries.map((e) => ({ e, s: score(q, `${e.label} ${e.detail || ''}`) })).filter((x) => x.s >= 0)
      .sort((a, b) => b.s - a.s || (a.e.kind === 'Dashboard' ? -1 : 1)).slice(0, 40).map((x) => x.e);
    active = Math.min(active, Math.max(0, shown.length - 1));
    clear(list);
    if (!shown.length) list.append(h('div', { class: 'palette-empty', text: 'Sonuç yok' }));
    shown.forEach((entry, i) => list.append(h('button', { type: 'button', role: 'option', id: `palette-opt-${i}`, 'aria-selected': String(i === active), class: ['palette-item', i === active ? 'on' : ''].join(' '),
      onMousemove: () => { if (active !== i) { active = i; draw(); } }, onClick: () => choose(entry) },
    icon(entry.icon), h('span', { class: 'palette-label', text: entry.label }), entry.detail ? h('span', { class: 'palette-detail', text: entry.detail }) : null, h('span', { class: 'palette-kind', text: entry.kind }))));
    field.setAttribute('aria-activedescendant', shown.length ? `palette-opt-${active}` : '');
    list.querySelector('.on')?.scrollIntoView({ block: 'nearest' });
  }
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); active = (active + (e.key === 'ArrowDown' ? 1 : -1) + shown.length) % Math.max(1, shown.length); draw(); return; }
    if (e.key === 'Enter' && shown[active]) { e.preventDefault(); choose(shown[active]); }
  }
  field.addEventListener('input', () => { active = 0; draw(); });
  document.addEventListener('keydown', onKey, true);
  document.body.append(backdrop);
  open = field;
  draw();
  field.focus();
  get('/api/search').then((dashboards) => {
    if (!open) return;
    entries = [...dashboards.map((d) => {
      const smart = (d.tags || []).includes('akıllı');
      return { label: d.title, detail: d.folderTitle || 'Genel', kind: smart ? 'Akıllı dashboard' : 'Dashboard', icon: smart ? 'report' : 'apps', run: () => navigate(smart ? `/smart/${d.uid}` : `/d/${d.uid}`) };
    }), ...staticEntries(app)];
    draw();
  }).catch(() => {});
}

const SHORTCUTS = [
  ['Genel', [['Ctrl + K', 'Komut paleti: dashboard, sayfa veya işlem ara'], ['?', 'Bu kısayol listesi'], ['Esc', 'Açık pencereyi kapat']]],
  ['Dashboard', [['Ctrl + Enter', 'Keşfet’te sorguyu çalıştır'], ['Ctrl + S', 'Kaydet']]],
  ['Akıllı dashboard', [['Ctrl + Z / Ctrl + Y', 'Geri al / yinele'], ['Ctrl + D', 'Seçili öğeyi çoğalt'], ['Delete', 'Seçili öğeyi sil'],
    ['← ↑ → ↓', 'Seçili öğeyi 1 hücre kaydır (Shift ile 4)'], ['Shift + tıklama', 'Çoklu seçim (hizala, eşit boyut, dağıt)'], ['Esc', 'Seçimi kaldır'], ['Ctrl + S', 'Kaydet']]],
];

function shortcutsDialog() {
  if (document.querySelector('.shortcuts-dialog')) return;
  const opener = document.activeElement;
  const closeBtn = h('button', { type: 'button', class: 'btn', text: 'Kapat' });
  const box = h('div', { class: 'palette shortcuts-dialog', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Klavye kısayolları' },
    h('div', { class: 'palette-search' }, icon('key'), h('b', { text: 'Klavye kısayolları' })),
    h('div', { class: 'palette-list' }, SHORTCUTS.map(([group, rows]) => h('section', h('h3', { class: 'section-heading', text: group }),
      h('dl', { class: 'shortcut-list' }, rows.map(([k, v]) => [h('dt', h('kbd', { text: k })), h('dd', { text: v })]))))),
    h('div', { class: 'palette-hint' }, h('span', { text: 'Esc ile kapatın' }), closeBtn));
  const backdrop = h('div', { class: 'palette-backdrop', onMousedown: (e) => { if (e.target === backdrop) close(); } }, box);
  const onKey = (e) => { if (e.key === 'Escape') { e.preventDefault(); close(); } };
  function close() { backdrop.remove(); document.removeEventListener('keydown', onKey, true); if (opener && opener.focus) opener.focus(); }
  closeBtn.addEventListener('click', close);
  document.addEventListener('keydown', onKey, true);
  document.body.append(backdrop);
  closeBtn.focus();
}

export function installPalette(app) {
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(app); return; }
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '') || document.activeElement?.isContentEditable;
    if (e.key === '?' && !typing && !e.ctrlKey && !e.metaKey) { e.preventDefault(); shortcutsDialog(); }
  });
}
