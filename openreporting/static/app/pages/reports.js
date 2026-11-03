// Reports: list, editor (dashboard → PDF/Excel/CSV with group sections), preview, runs, schedules.
import { h, button, input, select, textarea, field, toggle, toast, confirmDialog, fmtDateTime, timeAgo, loading, clear, downloadBlob, modal } from '../dom.js';
import { icon } from '../icons.js';
import { get, post, put, del, api } from '../api.js';
import { navigate, setBreadcrumbs } from '../router.js';
import { QUICK_RANGES, effectiveZone } from '../time.js';
import { resolveVariables, ALL } from '../variables.js';
import { preparePreviewWindow } from '../preview.js';

const LOGO_MAX_BYTES = 1_000_000;

const readAsDataUrl = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(file);
});

// Customer logo for the PDF: uploaded once, validated and re-encoded by the server, referenced by id in the config.
function logoPicker(cfg, canEdit) {
  const wrap = h('div', { class: 'logo-picker' });
  const fileIn = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp,image/gif', hidden: true, onchange: async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    if (file.size > LOGO_MAX_BYTES) { toast('Logo en fazla 1 MB olabilir', 'error'); return; }
    try {
      const res = await post('/api/dash-reports/logos', { data: await readAsDataUrl(file) });
      cfg.logo_id = res.id;
      draw();
      toast('Logo yüklendi; raporu kaydetmeyi unutmayın', 'ok');
    } catch (err) { toast(err.message, 'error'); }
  } });
  const draw = () => {
    const preview = h('div', { class: 'logo-preview' }, cfg.logo_id
      ? h('img', { src: `/api/dash-reports/logos/${encodeURIComponent(cfg.logo_id)}`, alt: 'Müşteri logosu' })
      : h('span', { class: 'muted', text: 'Logo yok' }));
    wrap.replaceChildren(preview, fileIn,
      canEdit ? h('div', { class: 'toolbar' },
        button(cfg.logo_id ? 'Değiştir' : 'Logo yükle', { icon: 'upload', size: 'sm', onClick: () => fileIn.click() }),
        cfg.logo_id ? button('Kaldır', { icon: 'trash', size: 'sm', onClick: () => { cfg.logo_id = null; draw(); } }) : null) : null,
      cfg.logo_id ? h('div', { class: 'toolbar' },
        toggle('Kapakta göster', cfg.logo_on_cover, (v) => { cfg.logo_on_cover = v; }),
        toggle('Her sayfanın başlığında göster', cfg.logo_on_pages, (v) => { cfg.logo_on_pages = v; })) : null);
  };
  draw();
  return wrap;
}

const STATUS = { queued: ['Kuyrukta', 'info'], running: ['Çalışıyor', 'info'], completed: ['Tamamlandı', 'ok'], partial: ['Kısmi veri', 'warn'],
  failed: ['Başarısız', 'err'], blocked: ['Engellendi', 'err'], needs_review: ['İnceleme gerekli', 'warn'] };
const DELIVERY = { not_requested: 'E-posta yok', disabled: 'E-posta kapalı', pending: 'Gönderilecek', sending: 'Gönderiliyor', sent: 'Gönderildi',
  failed: 'Sunucu reddetti', partial_rejected: 'Bazı alıcılara gönderilemedi (manuel kontrol)',
  unknown: 'Belirsiz (manuel kontrol)', blocked_partial: 'Kısmi veri nedeniyle gönderilmedi', blocked_revalidation: 'Yeniden doğrulama engelledi', blocked_too_large: 'Ekler boyut sınırını aşıyor' };
const CADENCES = [{ value: 'hourly', label: 'Saatlik' }, { value: 'daily', label: 'Günlük' }, { value: 'weekly', label: 'Haftalık' }, { value: 'monthly', label: 'Aylık' }, { value: 'yearly', label: 'Yıllık' }];
const WEEKDAYS = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar'];
const REPORT_RANGES = [['now-1d/d', 'now-1d/d', 'Dün'], ['now-1w/w', 'now-1w/w', 'Geçen hafta'], ['now-1M/M', 'now-1M/M', 'Geçen ay'], ['now-1y/y', 'now-1y/y', 'Geçen yıl'],
  ...QUICK_RANGES.filter(([f, t]) => t === 'now').map(([f, t, l]) => [f, t, l])];

function statusBadge(status) { const [label, kind] = STATUS[status] || [status, '']; return h('span', { class: `badge ${kind}`, text: label }); }

function fileLinks(run) {
  const links = [];
  for (const kind of ['pdf', 'xlsx', 'csv', 'manifest']) {
    if (!run.files || !run.files[kind]) continue;
    links.push(h('a', { class: 'btn sm', href: `/api/report-runs/${run.id}/files/${kind}`, download: '', title: `${kind.toUpperCase()} indir` }, icon('download'), kind === 'manifest' ? 'JSON' : kind.toUpperCase()));
  }
  return h('span', { class: 'toolbar', style: { gap: '4px' } }, links);
}

export function runsTable(runs, { showReport = true } = {}) {
  if (!runs.length) return h('p', { class: 'muted', text: 'Henüz çalıştırma yok.' });
  const table = h('table', { class: 'list' }, h('tr', [showReport ? 'Rapor' : null, 'Dönem', 'Durum', 'E-posta', 'Oluşturulma', 'Dosyalar'].filter(Boolean).map((t) => h('th', { text: t }))));
  for (const r of runs) {
    table.append(h('tr', showReport ? h('td', h('a', { href: `/reports/${r.report_id}`, 'data-link': '', text: r.report_name })) : null,
      h('td', { class: 'nowrap', text: `${fmtDateTime(r.period_start)} → ${fmtDateTime(r.period_end)}` }),
      h('td', statusBadge(r.status), r.error ? h('div', { class: 'hint', text: r.error }) : null,
        r.warnings && r.warnings.length ? h('div', { class: 'hint', title: r.warnings.join('\n'), text: `${r.warnings.length} uyarı` }) : null),
      h('td', { class: 'hint', text: DELIVERY[r.delivery_status] || r.delivery_status }),
      h('td', { class: 'nowrap', text: timeAgo(r.created_at), title: fmtDateTime(r.created_at) }),
      h('td', fileLinks(r))));
  }
  return table;
}

// Pipeline problems of the last 30 days (failed runs, disabled schedules); also shown without SMTP.
function notificationCard(events) {
  const since = Date.now() - 30 * 86400000;
  const recent = (events || []).filter((e) => Date.parse(e.created_at) >= since);
  if (!recent.length) return [];
  const list = h('ul', { class: 'notification-list' }, recent.map((e) => h('li',
    h('span', { class: 'badge warn', text: fmtDateTime(e.created_at) }), ' ',
    h('a', { href: `/reports/${encodeURIComponent(e.report_id)}`, 'data-link': '', text: e.report_name }), ` — ${e.title}`)));
  return [h('div', { class: 'alert warn', role: 'status' }, h('b', { text: 'Dikkat gerektiren rapor olayları' }), list)];
}

export async function reportsPage(root, { app }) {
  setBreadcrumbs([{ label: 'Raporlar' }]);
  const canEdit = ['admin', 'editor'].includes(app.user.role);
  const page = h('div', { class: 'page' }, loading());
  root.append(page);
  let timer = null;
  let stopped = false;
  const draw = async () => {
    const [reports, runs, schedules, events] = await Promise.all([get('/api/dash-reports'), get('/api/report-runs?limit=50'), get('/api/report-schedules'),
      get('/api/report-notifications?limit=10').catch(() => [])]);
    if (stopped) return;
    clear(page);
    page.append(h('div', { class: 'page-header' }, h('div', h('h1', icon('report'), 'Raporlar'),
      h('p', { class: 'sub', text: 'Dashboard’ları PDF / Excel / CSV rapora dönüştürün; host grubu değişkenine göre her host için ayrı bölüm üretin, zamanlayın ve e-postayla gönderin.' })),
    canEdit ? button('Yeni rapor', { icon: 'plus', variant: 'primary', onClick: () => navigate('/reports/new') }) : null));
    page.append(...notificationCard(events));
    if (!reports.length) {
      page.append(h('div', { class: 'empty-state' }, h('h2', { class: 'section-heading', text: 'Henüz rapor yok' }),
        h('p', { text: 'Bir dashboard seçip rapor tanımı oluşturun. Örnek: "Ağ Operasyon Özeti" dashboard’u, $host değişkenine göre bölümlenmiş haftalık PDF.' }),
        canEdit ? h('div', { class: 'toolbar' }, button('Yeni rapor', { icon: 'plus', variant: 'primary', onClick: () => navigate('/reports/new') })) : null));
    } else {
      const table = h('table', { class: 'list' }, h('tr', ['Rapor', 'Dashboard', 'Bölümleme', 'Biçimler', 'Zamanlama', 'Son durum', ''].map((t) => h('th', { text: t }))));
      for (const r of reports) {
        table.append(h('tr', h('td', h('a', { href: `/reports/${r.id}`, 'data-link': '' }, h('b', { text: r.name }))),
          h('td', r.dashboard_title ? h('a', { href: `/d/${r.dashboard_uid}`, 'data-link': '', text: r.dashboard_title }) : h('span', { class: 'badge err', text: 'dashboard yok' })),
          h('td', { text: r.config.split_by ? `$${r.config.split_by}` : '—' }), h('td', { text: r.config.formats.join(', ').toUpperCase() }),
          h('td', r.active_schedules ? h('span', { class: 'badge ok', text: `${r.active_schedules} etkin` }) : h('span', { class: 'faint', text: 'yok' })),
          h('td', r.last_status ? statusBadge(r.last_status) : h('span', { class: 'faint', text: '—' }), r.last_run_at ? h('div', { class: 'hint', text: timeAgo(r.last_run_at) }) : null),
          h('td', { class: 'actions' }, canEdit ? button('Şimdi çalıştır', { size: 'sm', icon: 'play', onClick: async () => {
            try { await post(`/api/dash-reports/${r.id}/runs`, {}); toast('Rapor kuyruğa alındı; worker üretiyor', 'ok'); draw(); } catch (err) { toast(err.message, 'error'); }
          } }) : null, button('Aç', { size: 'sm', onClick: () => navigate(`/reports/${r.id}`) }))));
      }
      page.append(h('div', { class: 'card' }, table));
    }
    if (schedules.length) {
      const table = h('table', { class: 'list' }, h('tr', ['Rapor', 'Periyot', 'Sonraki', 'Alıcılar', 'Durum'].map((t) => h('th', { text: t }))));
      for (const s of schedules) table.append(h('tr', h('td', { text: s.report_name }), h('td', { text: (CADENCES.find((c) => c.value === s.cadence) || {}).label || s.cadence }),
        h('td', { text: fmtDateTime(s.next_due) }), h('td', { text: s.recipients.length ? s.recipients.join(', ') : 'yalnızca arşiv' }),
        h('td', s.enabled ? h('span', { class: 'badge ok', text: 'etkin' }) : h('span', { class: 'badge', text: 'pasif' }))));
      page.append(h('h2', { class: 'section-heading', text: 'Zamanlamalar' }), h('div', { class: 'card' }, table));
    }
    page.append(h('div', { class: 'toolbar', style: { justifyContent: 'space-between' } }, h('h2', { class: 'section-heading', text: 'Son çalıştırmalar ve arşiv', style: { margin: '0' } }), button('Yenile', { icon: 'refresh', size: 'sm', onClick: draw })),
      h('div', { class: 'card', style: { marginTop: '10px' } }, runsTable(runs)));
    clearTimeout(timer);
    if (runs.some((r) => r.status === 'queued' || r.status === 'running')) timer = setTimeout(poll, 4000);
  };
  // A transient error must not stop status polling for good; retry with a longer delay.
  function poll() { draw().catch(() => { if (!stopped) timer = setTimeout(poll, 10000); }); }
  await draw();
  return () => { stopped = true; clearTimeout(timer); };
}

export async function reportEditPage(root, { id, query, app }) {
  const params = new URLSearchParams(query || '');
  const canEdit = ['admin', 'editor'].includes(app.user.role);
  const isNew = !id;
  const existing = isNew ? null : await get(`/api/dash-reports/${encodeURIComponent(id)}`);
  const settings = await get('/api/frontend/settings');
  const dashboardsList = await get('/api/search');
  const cfg = existing ? JSON.parse(JSON.stringify(existing.config)) : {
    name: '', description: '', dashboard_uid: params.get('dashboard') || (dashboardsList[0] || {}).uid || '', time_range: { from: 'now-1d/d', to: 'now-1d/d' },
    timezone: 'Europe/Istanbul', variables: {}, split_by: null, panel_ids: [], include_collapsed: true, layout: 'grid', orientation: 'landscape', paper: 'A4',
    formats: ['pdf', 'xlsx'], cover: true, toc: true, footer_text: '', table_max_rows: 500, send_partial: false, email_subject: '', email_message: '' };
  cfg.logo_id = cfg.logo_id || null;
  cfg.logo_on_cover = cfg.logo_on_cover !== false;
  cfg.logo_on_pages = cfg.logo_on_pages !== false;
  setBreadcrumbs([{ label: 'Raporlar', href: '/reports' }, { label: existing ? existing.name : 'Yeni rapor' }], root);
  const page = h('div', { class: 'page' });
  root.append(page);
  const dashHost = h('div');
  let dashboard = null;
  let timer = null;

  let loadSeq = 0;
  const loadDashboard = async () => {
    const seq = ++loadSeq;
    const current = () => seq === loadSeq;
    clear(dashHost);
    if (!cfg.dashboard_uid) { dashHost.append(h('p', { class: 'muted', text: 'Önce bir dashboard seçin.' })); return; }
    dashHost.append(loading('Dashboard ve değişkenler yükleniyor…'));
    try {
      const loaded = (await get(`/api/dashboards/uid/${encodeURIComponent(cfg.dashboard_uid)}`)).dashboard;
      if (!current()) return;
      dashboard = loaded;
    } catch (err) { if (current()) { clear(dashHost); dashHost.append(h('div', { class: 'alert error', text: err.message })); } return; }
    const vars = (dashboard.templating || {}).list || [];
    let resolved = {};
    if (vars.length) {
      try { resolved = (await resolveVariables(dashboard, cfg.variables, cfg.time_range, cfg.timezone, cfg.dashboard_uid)).variables; } catch (err) { if (current()) toast(err.message, 'error'); }
      if (!current()) return;
    }
    clear(dashHost);
    const varFields = vars.filter((v) => v.type !== 'constant').map((v) => {
      const r = resolved[v.name] || { options: [] };
      const current = cfg.variables[v.name] ?? r.value;
      if (v.type === 'textbox') return field(v.label || v.name, input({ value: Array.isArray(current) ? current[0] : current || '', onChange: (e) => { cfg.variables[v.name] = e.target.value; } }));
      const opts = [...(v.includeAll ? [{ value: ALL, label: 'Tümü' }] : []), ...r.options.map((o) => ({ value: o.value, label: o.text }))];
      const el = h('select', { class: 'input', multiple: v.multi || undefined, size: v.multi ? Math.min(6, opts.length || 1) : undefined,
        onchange: (e) => { const sel = [...e.target.selectedOptions].map((o) => o.value); cfg.variables[v.name] = v.multi ? sel : sel[0]; } },
      opts.map((o) => h('option', { value: o.value, text: o.label, selected: (Array.isArray(current) ? current : [current]).includes(o.value) })));
      return field(v.label || v.name, el, v.multi ? 'Ctrl ile çoklu seçim' : null);
    });
    const splitSel = select([{ value: '', label: 'Bölümleme yok (tek bölüm)' }, ...vars.filter((v) => ['query', 'custom'].includes(v.type)).map((v) => ({ value: v.name, label: `$${v.name} – her değer için ayrı bölüm` }))],
      cfg.split_by || '', (val) => { cfg.split_by = val || null; });
    const panels = (dashboard.panels || []).flatMap((p) => (p.type === 'row' ? [p, ...(p.panels || [])] : [p])).filter((p) => p.type !== 'row');
    const selected = new Set(cfg.panel_ids || []);
    const panelBox = h('div', { class: 'chips' }, panels.map((p) => h('label', { class: 'chip', style: { cursor: 'pointer' } },
      h('input', { type: 'checkbox', checked: !selected.size || selected.has(p.id), onchange: (e) => {
        if (!selected.size) panels.forEach((x) => selected.add(x.id));
        if (e.target.checked) selected.add(p.id); else selected.delete(p.id);
        cfg.panel_ids = selected.size === panels.length ? [] : [...selected];
      } }), p.title || `${p.type} #${p.id}`)));
    dashHost.append(
      vars.length ? h('div', h('h3', { class: 'subsection-heading', text: 'Değişken değerleri' }), h('div', { class: 'form-grid' }, varFields)) : h('p', { class: 'muted', text: 'Bu dashboard’da değişken yok.' }),
      field('Grup bazlı bölümleme', splitSel, 'Örn. $host seçilirse gruptaki her host için başlıklı ayrı bölüm (ve içindekiler) üretilir.'),
      field(`Rapora dahil paneller (${panels.length})`, panelBox, 'Hiçbiri seçili değilse tüm paneller dahil edilir.'));
  };

  const rangeKey = `${cfg.time_range.from}|${cfg.time_range.to}`;
  const rangeSel = select([...REPORT_RANGES.map(([f, t, l]) => ({ value: `${f}|${t}`, label: l })), { value: 'custom', label: 'Özel…' }],
    REPORT_RANGES.some(([f, t]) => `${f}|${t}` === rangeKey) ? rangeKey : 'custom', (v) => {
      if (v !== 'custom') { const [f, t] = v.split('|'); cfg.time_range = { from: f, to: t }; fromIn.value = f; toIn.value = t; }
    });
  const fromIn = input({ value: cfg.time_range.from, onChange: (e) => { cfg.time_range.from = e.target.value; rangeSel.value = 'custom'; } });
  const toIn = input({ value: cfg.time_range.to, onChange: (e) => { cfg.time_range.to = e.target.value; rangeSel.value = 'custom'; } });
  const formatBoxes = h('div', { class: 'toolbar' }, ['pdf', 'xlsx', 'csv'].map((f) => toggle(f.toUpperCase(), cfg.formats.includes(f), (on) => {
    cfg.formats = on ? [...new Set([...cfg.formats, f])] : cfg.formats.filter((x) => x !== f);
  })));
  const dashSel = select([{ value: '', label: 'Dashboard seçin' }, ...dashboardsList.map((d) => ({ value: d.uid, label: `${d.folderTitle} / ${d.title}` }))], cfg.dashboard_uid, (v) => {
    cfg.dashboard_uid = v; cfg.variables = {}; cfg.split_by = null; cfg.panel_ids = []; loadDashboard();
  });

  // The PDF tab is opened inside the click handler (popup blockers reject window.open after an await)
  // and pointed at the rendered file once it arrives; if the browser blocked it the file is downloaded.
  const preview = async (format) => {
    const win = format === 'pdf' ? window.open('', '_blank') : null;
    preparePreviewWindow(win);
    try {
      const res = await api('/api/dash-reports/preview', { method: 'POST', body: { ...cfg, name: cfg.name || 'Önizleme', format, max_sections: 3 }, raw: true });
      const blob = await res.blob();
      if (format === 'pdf' && win && !win.closed) {
        const url = URL.createObjectURL(blob);
        win.location.href = url;
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      } else downloadBlob(`onizleme.${format}`, blob);
    } catch (err) {
      if (win && !win.closed) win.close();
      toast(err.message, 'error');
    }
  };
  const save = async () => {
    if (!cfg.name.trim()) { toast('Rapor adı girin', 'error'); return null; }
    try {
      if (isNew) {
        const res = await post('/api/dash-reports', cfg);
        toast('Rapor kaydedildi', 'ok');
        navigate(`/reports/${res.id}`, { replace: true, force: true });
        return res.id;
      }
      await put(`/api/dash-reports/${id}`, cfg);
      toast('Rapor güncellendi', 'ok');
      return id;
    } catch (err) { toast(err.message, 'error'); return null; }
  };

  const form = h('div', { class: 'split-2' },
    h('div', h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Genel' }),
      field('Rapor adı', input({ value: cfg.name, placeholder: 'Ör. WAN Router Haftalık Performans', onChange: (e) => { cfg.name = e.target.value; } })),
      field('Açıklama', textarea({ value: cfg.description, rows: 2, onChange: (e) => { cfg.description = e.target.value; } })),
      field('Dashboard', dashSel),
      h('div', { class: 'form-grid' }, field('Zaman aralığı', rangeSel), field('Saat dilimi', select(['Europe/Istanbul', 'UTC', 'Europe/London', 'Europe/Berlin'].map((z) => ({ value: z, label: z })), cfg.timezone, (v) => { cfg.timezone = v; }))),
      h('div', { class: 'form-grid' }, field('Başlangıç', fromIn), field('Bitiş', toIn)),
      h('p', { class: 'hint', text: 'Zamanlanmış çalıştırmalarda varsayılan olarak "önceki tam dönem" (dün, geçen hafta, geçen ay) kullanılır.' })),
    h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Dashboard içeriği' }), dashHost)),
    h('div', h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Çıktı ve düzen' }),
      field('Biçimler', formatBoxes),
      h('div', { class: 'form-grid' },
        field('Sayfa düzeni', select([{ value: 'grid', label: 'Dashboard ızgarası (birebir)' }, { value: 'simple', label: 'Akış (panel başına tam genişlik)' }], cfg.layout, (v) => { cfg.layout = v; })),
        field('Yön', select([{ value: 'landscape', label: 'Yatay' }, { value: 'portrait', label: 'Dikey' }], cfg.orientation, (v) => { cfg.orientation = v; })),
        field('Kâğıt', select(['A4', 'A3', 'Letter'], cfg.paper, (v) => { cfg.paper = v; })),
        field('Tablo satır sınırı (PDF)', input({ type: 'number', value: cfg.table_max_rows, min: 10, max: 20000, onChange: (e) => { cfg.table_max_rows = Number(e.target.value); } }))),
      h('div', { class: 'toolbar' }, toggle('Kapak sayfası', cfg.cover, (v) => { cfg.cover = v; }), toggle('İçindekiler', cfg.toc, (v) => { cfg.toc = v; }),
        toggle('Daraltılmış satırları dahil et', cfg.include_collapsed, (v) => { cfg.include_collapsed = v; })),
      field('Müşteri logosu', logoPicker(cfg, canEdit),
        'PNG, JPG, WebP veya GIF; en fazla 1 MB. Saydam arka planlı PNG en iyi sonucu verir. Kapakta sağ üstte, sayfalarda başlığın sağında yer alır.'),
      field('Alt bilgi metni', input({ value: cfg.footer_text, placeholder: 'Ör. Ağ Operasyon Merkezi · Gizli', onChange: (e) => { cfg.footer_text = e.target.value; } }))),
    h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'E-posta' }),
      settings.mailEnabled ? null : h('div', { class: 'alert warn', text: 'SMTP kapalı: raporlar arşivlenir, e-posta gönderilmez. Etkinleştirmek için /etc/openreporting/openreporting.env içinde OPENREPORTING_MAIL_ENABLED=true ve SMTP ayarlarını yapın.' }),
      field('Konu şablonu', input({ value: cfg.email_subject, placeholder: '{report} | {from} – {to}', onChange: (e) => { cfg.email_subject = e.target.value; } })),
      field('Mesaj', textarea({ value: cfg.email_message, rows: 3, placeholder: 'Rapor ektedir.', onChange: (e) => { cfg.email_message = e.target.value; } })),
      toggle('Kısmi veri (hata / NO DATA) olsa da gönder', cfg.send_partial, (v) => { cfg.send_partial = v; }),
      h('p', { class: 'hint', text: 'Varsayılan güvenli davranış: eksik veri içeren raporlar e-postayla gönderilmez, yalnızca arşivlenir.' }))));
  page.append(h('div', { class: 'page-header' }, h('div', h('h1', icon('report'), existing ? existing.name : 'Yeni rapor'), existing ? h('p', { class: 'sub', text: `Revizyon ${existing.revision} · güncellendi ${timeAgo(existing.updated_at)}` }) : null),
    h('div', { class: 'toolbar' }, button('PDF önizle', { icon: 'eye', onClick: () => preview('pdf') }), button('Excel önizle', { icon: 'download', onClick: () => preview('xlsx') }),
      canEdit ? button('Kaydet', { icon: 'save', variant: 'primary', onClick: save }) : null,
      canEdit && !isNew ? button('Şimdi çalıştır', { icon: 'play', onClick: async () => {
        try { await post(`/api/dash-reports/${id}/runs`, {}); toast('Rapor kuyruğa alındı', 'ok'); drawRuns(); } catch (err) { toast(err.message, 'error'); }
      } }) : null,
      canEdit && !isNew ? button('', { icon: 'trash', title: 'Raporu sil', onClick: async () => {
        if (!(await confirmDialog('Raporu sil', 'Rapor, zamanlamaları ve arşiv kayıtları silinecek.', { danger: true, okText: 'Sil' }))) return;
        try { await del(`/api/dash-reports/${id}`); navigate('/reports'); } catch (err) { toast(err.message, 'error'); }
      } }) : null)), form);
  await loadDashboard();
  if (isNew) return () => {};

  const scheduleHost = h('div', { class: 'card' });
  const runsHost = h('div', { class: 'card' });
  page.append(h('h2', { class: 'section-heading', text: 'Zamanlamalar' }), scheduleHost, h('h2', { class: 'section-heading', text: 'Çalıştırma geçmişi' }), runsHost);
  const drawSchedules = async () => {
    const list = await get(`/api/dash-reports/${id}/schedules`);
    clear(scheduleHost);
    if (list.length) {
      const table = h('table', { class: 'list' }, h('tr', ['Periyot', 'Zaman', 'Dönem', 'Alıcılar', 'Sonraki', 'Durum', ''].map((t) => h('th', { text: t }))));
      for (const s of list) {
        const when = s.cadence === 'hourly' ? `her saat :${String(s.minute).padStart(2, '0')}` : `${s.cadence === 'weekly' ? `${WEEKDAYS[s.weekday]} ` : s.cadence === 'monthly' ? `ayın ${s.month_day}. günü ` : ''}${String(s.hour).padStart(2, '0')}:${String(s.minute).padStart(2, '0')} (${s.timezone})`;
        table.append(h('tr', h('td', { text: (CADENCES.find((c) => c.value === s.cadence) || {}).label }), h('td', { text: when }),
          h('td', { text: s.range_mode === 'report' ? 'Rapordaki aralık' : 'Önceki tam dönem' }), h('td', { text: s.recipients.length ? s.recipients.join(', ') : 'yalnızca arşiv' }),
          h('td', { text: fmtDateTime(s.next_due) }), h('td', s.enabled ? h('span', { class: 'badge ok', text: 'etkin' }) : h('span', { class: 'badge', text: 'pasif' })),
          h('td', { class: 'actions' }, canEdit ? button('Düzenle', { size: 'sm', onClick: () => scheduleDialog(s) }) : null,
            canEdit ? button('', { icon: 'trash', size: 'sm', title: 'Zamanlamayı sil', onClick: async () => {
              if (!(await confirmDialog('Zamanlamayı sil', 'Bu zamanlama silinecek; geçmiş çalıştırmalar arşivde kalır.', { danger: true, okText: 'Sil' }))) return;
              try { await del(`/api/report-schedules/${s.id}`); toast('Zamanlama silindi', 'ok'); drawSchedules(); } catch (err) { toast(err.message, 'error'); }
            } }) : null)));
      }
      scheduleHost.append(table);
    } else scheduleHost.append(h('p', { class: 'muted', text: 'Zamanlama yok.' }));
    if (canEdit) scheduleHost.append(button('Zamanlama ekle', { icon: 'plus', onClick: () => scheduleDialog(null) }));
  };
  const scheduleDialog = (s) => {
    const m = s ? { ...s, recipients: s.recipients.join(', ') } : { cadence: 'daily', timezone: cfg.timezone, hour: 8, minute: 0, weekday: 0, month_day: 1, range_mode: 'previous_period', recipients: '', enabled: false };
    const body = h('div');
    const draw = () => {
      clear(body);
      body.append(h('div', { class: 'form-grid' },
        field('Periyot', select(CADENCES, m.cadence, (v) => { m.cadence = v; draw(); })),
        m.cadence === 'weekly' ? field('Gün', select(WEEKDAYS.map((d, i) => ({ value: String(i), label: d })), String(m.weekday), (v) => { m.weekday = Number(v); })) : null,
        m.cadence === 'monthly' ? field('Ayın günü (1-28)', input({ type: 'number', min: 1, max: 28, value: m.month_day, onChange: (e) => { m.month_day = Number(e.target.value); } })) : null,
        m.cadence !== 'hourly' ? field('Saat', input({ type: 'number', min: 0, max: 23, value: m.hour, onChange: (e) => { m.hour = Number(e.target.value); } })) : null,
        field('Dakika', input({ type: 'number', min: 0, max: 59, value: m.minute, onChange: (e) => { m.minute = Number(e.target.value); } })),
        field('Saat dilimi', input({ value: m.timezone, onChange: (e) => { m.timezone = e.target.value; } })),
        field('Rapor dönemi', select([{ value: 'previous_period', label: 'Önceki tam dönem (dün / geçen hafta / geçen ay)' }, { value: 'report', label: 'Rapordaki zaman aralığı' }], m.range_mode, (v) => { m.range_mode = v; }))),
      field('Alıcılar (virgülle)', input({ value: m.recipients, placeholder: settings.recipientDomains.length ? `ornek@${settings.recipientDomains[0]}` : 'SMTP kapalı', onChange: (e) => { m.recipients = e.target.value; } }),
        settings.recipientDomains.length ? `İzinli alan adları: ${settings.recipientDomains.join(', ')}` : 'Alıcı alan adı izin listesi tanımlı değil (OPENREPORTING_ALLOWED_RECIPIENT_DOMAINS).'),
      toggle('Etkin (yalnızca yönetici)', !!m.enabled, (v) => { m.enabled = v; }));
    };
    draw();
    const dlg = modal({ title: s ? 'Zamanlamayı düzenle' : 'Yeni zamanlama', body, footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Kaydet', { variant: 'primary', onClick: async () => {
      const payload = { ...m, recipients: String(m.recipients || '').split(',').map((x) => x.trim()).filter(Boolean) };
      try {
        if (s) await put(`/api/dash-reports/${id}/schedules/${s.id}`, payload); else await post(`/api/dash-reports/${id}/schedules`, payload);
        dlg.close(); toast('Zamanlama kaydedildi', 'ok'); drawSchedules();
      } catch (err) { toast(err.message, 'error'); }
    } })] });
  };
  let stopped = false;
  const drawRuns = async () => {
    const runs = await get(`/api/dash-reports/${id}/runs`);
    if (stopped) return;
    clear(runsHost);
    runsHost.append(runsTable(runs, { showReport: false }));
    clearTimeout(timer);
    if (runs.some((r) => r.status === 'queued' || r.status === 'running')) timer = setTimeout(pollRuns, 3000);
  };
  function pollRuns() { drawRuns().catch(() => { if (!stopped) timer = setTimeout(pollRuns, 10000); }); }
  await Promise.all([drawSchedules(), drawRuns()]);
  return () => { stopped = true; clearTimeout(timer); };
}

export { effectiveZone };
