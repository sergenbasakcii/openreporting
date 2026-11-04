// Right-hand inspector of the smart dashboard editor: page/report settings or the selected element.
import { h, button, input, select, field, toast, clear, toggle } from '../dom.js';
import { icon } from '../icons.js';
import { post } from '../api.js';
import { PLUGINS } from '../panels/registry.js';
import { THRESHOLDS } from './templates.js';
import { timePicker, resolveRange, rangeLabel } from '../time.js';

export const CHART_TYPES = ['narrative', 'timeseries', 'barchart', 'stat', 'gauge', 'bargauge', 'table', 'piechart', 'donut', 'statusgrid', 'heatmap', 'statetimeline'];
export const LAYOUT_TYPES = ['text', 'image', 'divider', 'reportinfo'];
const REDUCING = ['stat', 'gauge', 'bargauge', 'piechart', 'donut', 'statusgrid'];
const UNITS = [{ value: '', label: 'Otomatik' }, { value: 'percent', label: 'Yüzde (%)' }, { value: 'bytes', label: 'Bayt' }, { value: 'bps', label: 'bit/sn' },
  { value: 'Bps', label: 'Bayt/sn' }, { value: 'ms', label: 'Milisaniye' }, { value: 's', label: 'Saniye' }, { value: 'short', label: 'Sayı (kısa)' }, { value: 'none', label: 'Birimsiz' }];
export const COMBINE = [{ value: '', label: 'Ayrı ayrı (her host/item)' }, { value: 'averageSeries', label: 'Tek seri · ortalama' },
  { value: 'sumSeries', label: 'Tek seri · toplam' }, { value: 'maxSeries', label: 'Tek seri · en yüksek' }, { value: 'minSeries', label: 'Tek seri · en düşük' }];
const COMBINERS = COMBINE.map((c) => c.value).filter(Boolean);
const CALCS = [{ value: 'lastNotNull', label: 'Son değer' }, { value: 'mean', label: 'Ortalama' }, { value: 'max', label: 'En yüksek' }, { value: 'min', label: 'En düşük' }, { value: 'sum', label: 'Toplam' }];

const readAsDataUrl = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(new Error('Dosya okunamadı'));
  reader.readAsDataURL(file);
});

// Upload → validated, re-encoded PNG on the server; returns its id.
export function imagePicker(current, onPick, label = 'Görsel yükle') {
  const file = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp,image/gif', hidden: true, onChange: async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    if (f.size > 1_000_000) { toast('Görsel en fazla 1 MB olabilir', 'error'); return; }
    try { const res = await post('/api/dash-reports/logos', { data: await readAsDataUrl(f) }); onPick(res.id); toast('Görsel yüklendi', 'ok'); } catch (err) { toast(err.message, 'error'); }
  } });
  return h('div', { class: 'image-picker' },
    current ? h('img', { src: `/api/dash-reports/logos/${encodeURIComponent(current)}`, alt: 'Seçili görsel' }) : h('span', { class: 'hint', text: 'Görsel yok' }),
    h('div', { class: 'toolbar' }, button(label, { size: 'sm', icon: 'upload', onClick: () => file.click() }), current ? button('Kaldır', { size: 'sm', variant: 'ghost', onClick: () => onPick(null) }) : null), file);
}

const path = (obj, keys, fallback) => keys.reduce((o, k) => (o && o[k] !== undefined ? o[k] : undefined), obj) ?? fallback;

function thresholdPreset(panel) {
  const t = JSON.stringify(panel.fieldConfig?.defaults?.thresholds || null);
  return Object.entries(THRESHOLDS).find(([, v]) => JSON.stringify(v) === t)?.[0] || (t === 'null' ? 'none' : 'custom');
}

const PERIODS = [['now-7d', 'now', 'Son 7 gün'], ['now-30d', 'now', 'Son 30 gün'], ['now-90d', 'now', 'Son 90 gün'], ['now-6M', 'now', 'Son 6 ay'],
  ['now-1y', 'now', 'Son 1 yıl'], ['now/y', 'now', 'Bu yıl'], ['now-1y/y', 'now-1y/y', 'Geçen yıl'], ['now-1M/M', 'now-1M/M', 'Geçen ay']];

// Per-panel period: e.g. an interface traffic panel over the last year inside a 24-hour report.
function periodEditor(panel, change, timezone) {
  const own = panel.timeRange;
  const set = (range) => change(() => { if (range) panel.timeRange = range; else delete panel.timeRange; }, { refresh: panel, canvas: true });
  const picker = timePicker({ range: own || { from: 'now-1y', to: 'now' }, timezone, onChange: (r) => set({ from: String(r.from), to: String(r.to) }),
    getResolved: () => resolveRange(own || { from: 'now-1y', to: 'now' }, timezone) });
  return h('div', { class: 'period-editor' },
    h('div', { class: 'segmented period-mode', role: 'radiogroup', 'aria-label': 'Tarih aralığı kaynağı' },
      h('button', { type: 'button', role: 'radio', 'aria-checked': String(!own), class: own ? '' : 'on', onClick: () => set(null) }, 'Rapor aralığı'),
      h('button', { type: 'button', role: 'radio', 'aria-checked': String(!!own), class: own ? 'on' : '', onClick: () => { if (!own) set({ from: 'now-1y', to: 'now' }); } }, 'Panele özel')),
    own ? h('div', h('div', { class: 'period-chips' }, PERIODS.map(([from, to, label]) => h('button', { type: 'button', class: ['kw-chip', own.from === from && own.to === to ? 'set' : ''].join(' '), onClick: () => set({ from, to }) }, label))),
      h('div', { class: 'period-picker' }, h('span', { class: 'hint', text: 'veya takvimden seçin:' }), picker),
      h('p', { class: 'hint', text: `Seçili: ${rangeLabel(own, timezone)}. PDF’te panel başlığının yanında yazar; göreli aralıklar raporun bitiş anına göre hesaplanır.` }))
      : h('p', { class: 'hint', text: 'Panel, araç çubuğundaki rapor tarih aralığını izler.' }));
}

export function createInspector(ctx) {
  const el = h('aside', { class: 'smart-side', 'aria-label': 'Ayarlar' });
  const { change } = ctx;

  function pageSettings(model) {
    const s = model.smart;
    return [
      h('h2', { class: 'section-heading', text: 'Rapor ayarları' }),
      field('Başlık', input({ value: model.title, onChange: (e) => change((m) => { m.title = e.target.value.trim() || 'Akıllı dashboard'; }) })),
      field('Alt başlık', input({ value: s.subtitle, placeholder: 'ör. Haftalık altyapı raporu', onChange: (e) => change((m) => { m.smart.subtitle = e.target.value; }) })),
      field('Logo (sayfa başı)', imagePicker(s.logo_id, (id) => change((m) => {
        m.smart.logo_id = id;
        // Empty logo/image elements pick up the new report logo.
        for (const p of m.panels) if (p.type === 'image' && !p.options?.logo_id && id) p.options = { ...(p.options || {}), logo_id: id };
      }, { all: true }), 'Logo yükle')),
      field(null, toggle('Logoyu her sayfada göster', s.logo_on_pages !== false, (v) => change((m) => { m.smart.logo_on_pages = v; }))),
      field('Alt bilgi metni', input({ value: s.footer || '', placeholder: 'ör. Şirket adı · Gizli', onChange: (e) => change((m) => { m.smart.footer = e.target.value; }) })),
      field(null, toggle('Kapak sayfası ekle', !!s.cover, (v) => change((m) => { m.smart.cover = v; }))),
      h('h3', { class: 'section-heading', text: 'Rapor filtresi' }),
      field(null, toggle('Grup / host seçimi rapor genelinde olsun', !!s.filters, (v) => ctx.toggleFilters(v))),
      h('p', { class: 'hint', text: 'Açıkken sayfanın üstünde Grup ve Host seçicileri çıkar; panellerde “Rapor filtresini kullan” seçeneği tüm grafikleri tek seçimle değiştirir. PDF’i her host için ayrı sayfalarla da alabilirsiniz.' }),
      h('h3', { class: 'section-heading', text: 'Sayfa' }),
      h('div', { class: 'form-grid' },
        field('Kâğıt', select(['A4', 'A3', 'Letter'].map((v) => ({ value: v, label: v })), s.paper, (v) => change((m) => { m.smart.paper = v; }))),
        field('Yön', select([{ value: 'portrait', label: 'Dikey' }, { value: 'landscape', label: 'Yatay' }], s.orientation, (v) => ctx.setOrientation(v)))),
      field('Varsayılan veri kaynağı', select(ctx.sources.map((d) => ({ value: d.uid, label: d.name })), model.smartSource?.uid || ctx.preferred?.uid, (v) => change((m) => { m.smartSource = { uid: v }; }, { canvas: false }))),
      h('p', { class: 'hint', text: 'İpuçları: öğeyi seçip ok tuşlarıyla kaydırın (Shift ile 4 hücre), Ctrl+D çoğaltır, Delete siler, Ctrl+Z / Ctrl+Y geri alır / yineler, Ctrl+S kaydeder.' }),
    ];
  }

  function quickLayout(panel, rows) {
    const set = (pos) => change(() => { panel.smartPos = { ...panel.smartPos, ...pos }; }, { refresh: panel });
    const pos = panel.smartPos;
    return h('div', { class: 'quick-layout' },
      button('Tam genişlik', { size: 'sm', onClick: () => set({ x: 0, w: 24 }) }),
      button('Sol yarı', { size: 'sm', onClick: () => set({ x: 0, w: 12 }) }),
      button('Sağ yarı', { size: 'sm', onClick: () => set({ x: 12, w: 12 }) }),
      button('Üçte bir', { size: 'sm', onClick: () => set({ w: 8, x: Math.min(pos.x, 16) }) }),
      button('Yatay ortala', { size: 'sm', onClick: () => set({ x: Math.round((24 - pos.w) / 2) }) }),
      button('Daha yüksek', { size: 'sm', onClick: () => set({ h: Math.min(rows - pos.y, pos.h + 2) }) }),
      button('Daha alçak', { size: 'sm', onClick: () => set({ h: Math.max(2, pos.h - 2) }) }));
  }

  function chartOptions(panel) {
    const d = panel.fieldConfig?.defaults || {};
    const setDefaults = (patch) => change(() => { panel.fieldConfig = { ...(panel.fieldConfig || {}), overrides: panel.fieldConfig?.overrides || [], defaults: { ...(panel.fieldConfig?.defaults || {}), ...patch } }; }, { refresh: panel });
    const setOption = (patch) => change(() => { panel.options = { ...(panel.options || {}), ...patch }; }, { refresh: panel });
    const ds = ctx.dsOf(panel);
    const items = [
      panel.type === 'narrative' ? field('Konu', input({ value: panel.options?.subject || '', placeholder: panel.title || 'ör. CPU kullanımı', onChange: (e) => setOption({ subject: e.target.value }) }), 'Cümleler bu adla başlar; boşsa panel başlığı kullanılır. Eşik ve karşılaştırma seçenekleri de cümlelere yansır.') : null,
      field('Veri kaynağı', select(ctx.sources.map((s) => ({ value: s.uid, label: s.name })), ds?.uid, (v) => ctx.changeSource(panel, v))),
      h('div', { class: 'form-grid' },
        field('Birim', select(UNITS, d.unit || '', (v) => setDefaults({ unit: v || undefined }))),
        field('Ondalık', select([{ value: '', label: 'Otomatik' }, ...[0, 1, 2, 3].map((n) => ({ value: String(n), label: String(n) }))], d.decimals === undefined ? '' : String(d.decimals), (v) => setDefaults({ decimals: v === '' ? undefined : Number(v) })))),
    ];
    const target = panel.targets?.[0] || panel.smartDraft;
    if (target && target.host) {
      const current = (target.functions || []).find((f) => COMBINERS.includes(f.name || f.def?.name));
      items.push(field('Seriler', select(COMBINE, current ? current.name || current.def?.name : '', (v) => change(() => {
        const t = panel.targets?.[0] || panel.smartDraft;
        t.functions = [...(t.functions || []).filter((f) => !COMBINERS.includes(f.name || f.def?.name)), ...(v ? [{ name: v, params: [] }] : [])];
      }, { refresh: panel })), 'KPI kartlarında tek bir özet değer için “Tek seri” seçin.'));
    }
    if (REDUCING.includes(panel.type)) {
      items.push(field('Gösterilen değer', select(CALCS, path(panel, ['options', 'reduceOptions', 'calcs', 0], 'lastNotNull'), (v) => setOption({ reduceOptions: { ...(panel.options?.reduceOptions || {}), calcs: [v] } }))));
    }
    const preset = thresholdPreset(panel);
    items.push(field('Renk eşikleri', select([{ value: 'none', label: 'Yok (seri renkleri)' }, { value: 'high-bad', label: 'Yüksek kötü: 70 sarı · 90 kırmızı' }, { value: 'low-bad', label: 'Düşük kötü: 30 altı sarı · 10 altı kırmızı' }, ...(preset === 'custom' ? [{ value: 'custom', label: 'Özel (gelişmiş)' }] : [])],
      preset, (v) => { if (v === 'custom') return; setDefaults({ thresholds: THRESHOLDS[v] || undefined, color: v === 'none' ? undefined : { mode: 'thresholds' } }); })));
    if (preset !== 'none') {
      const steps = d.thresholds?.steps || [];
      items.push(h('div', { class: 'form-grid' }, steps.slice(1).map((step, i) => field(`${i === 0 ? 'Uyarı' : 'Kritik'} eşiği`, input({ type: 'number', value: step.value,
        onChange: (e) => setDefaults({ thresholds: { ...d.thresholds, steps: steps.map((s, j) => (j === i + 1 ? { ...s, value: Number(e.target.value) } : s)) } }) })))));
    }
    if (['stat', 'timeseries', 'barchart', 'narrative'].includes(panel.type)) {
      items.push(field('Karşılaştırma', select([{ value: '', label: 'Yok' }, { value: 'previous', label: 'Önceki dönemle karşılaştır' }], panel.options?.compare || '',
        (v) => setOption({ compare: v || undefined })), panel.type === 'stat' ? 'Değerin altında ▲/▼ yüzde değişim yazar.' : 'Önceki dönem kesikli çizgiyle gösterilir.'));
      if (panel.options?.compare && panel.type === 'stat') {
        items.push(field('Artış', select([{ value: 'neutral', label: 'Nötr (renksiz)' }, { value: 'down', label: 'Azalış iyi (CPU, hata, gecikme)' }, { value: 'up', label: 'Artış iyi (satış, erişilebilirlik)' }],
          panel.options?.compareGood || 'neutral', (v) => setOption({ compareGood: v }))));
      }
    }
    if (panel.type === 'stat') items.push(field('Renk kullanımı', select([{ value: 'value', label: 'Değer rengi' }, { value: 'background', label: 'Arka plan' }, { value: 'none', label: 'Renksiz' }], panel.options?.colorMode || 'value', (v) => setOption({ colorMode: v }))));
    if (['timeseries', 'barchart'].includes(panel.type)) {
      items.push(field('Açıklama (legend)', select([{ value: 'list', label: 'Liste' }, { value: 'table', label: 'Tablo (ort./maks./son)' }, { value: 'hidden', label: 'Gizli' }], path(panel, ['options', 'legend', 'displayMode'], 'list'),
        (v) => setOption({ legend: { ...(panel.options?.legend || {}), displayMode: v, showLegend: v !== 'hidden', placement: 'bottom', calcs: v === 'table' ? ['mean', 'max', 'lastNotNull'] : [] } }))));
    }
    items.push(h('h3', { class: 'section-heading', text: 'Tarih aralığı' }), periodEditor(panel, change, ctx.getModel().timezone));
    items.push(button('Gelişmiş sorgu', { icon: 'code', size: 'sm', onClick: () => ctx.editQuery(panel) }));
    return items;
  }

  function layoutOptions(panel) {
    const setOption = (patch) => change(() => { panel.options = { ...(panel.options || {}), ...patch }; }, { refresh: panel });
    if (panel.type === 'image') {
      return [field('Görsel', imagePicker(panel.options?.logo_id, (id) => setOption({ logo_id: id }))),
        field('Hizalama', select([{ value: 'left', label: 'Sola' }, { value: 'center', label: 'Ortaya' }, { value: 'right', label: 'Sağa' }], panel.options?.align || 'center', (v) => setOption({ align: v })))];
    }
    if (panel.type === 'divider') {
      return [field('Çizgi', select([{ value: 'brand', label: 'Marka renkli' }, { value: 'solid', label: 'Düz' }, { value: 'subtle', label: 'İnce gri' }], panel.options?.style || 'brand', (v) => setOption({ style: v }))),
        h('p', { class: 'hint', text: 'Başlık alanına bölüm adını yazın; $host gibi değişkenler kullanılabilir.' })];
    }
    if (panel.type === 'reportinfo') {
      return [field(null, toggle('Filtre seçimlerini göster', panel.options?.showVariables !== false, (v) => setOption({ showVariables: v }))),
        field('Not', input({ value: panel.options?.note || '', placeholder: 'ör. Hazırlayan: NOC ekibi', onChange: (e) => setOption({ note: e.target.value }) }))];
    }
    const area = h('textarea', { class: 'input', rows: 10, value: panel.options?.content || '', 'aria-label': 'Metin (Markdown)', onChange: (e) => setOption({ mode: 'markdown', content: e.target.value }) });
    return [field('Metin (Markdown)', area), h('p', { class: 'hint', text: '# Başlık, **kalın**, - madde. $host gibi değişkenler PDF’te değeriyle yazılır.' })];
  }

  function panelSettings(model, panel) {
    const types = [...CHART_TYPES, ...LAYOUT_TYPES].map((t) => ({ value: t, label: PLUGINS[t]?.name || t }));
    const layout = LAYOUT_TYPES.includes(panel.type);
    return [
      h('div', { class: 'toolbar', style: { justifyContent: 'space-between' } }, h('h2', { class: 'section-heading', style: { margin: 0 }, text: PLUGINS[panel.type]?.name || 'Öğe' }),
        button('Rapor ayarları', { size: 'sm', variant: 'ghost', onClick: () => ctx.select(null) })),
      field('Başlık', input({ value: panel.title || '', placeholder: layout ? 'İsteğe bağlı' : 'Panel başlığı', onChange: (e) => change(() => { panel.title = e.target.value; panel.titleLocked = true; }, { refresh: panel }) })),
      layout && panel.type !== 'text' ? null : field('Tür', select(types.filter((t) => (layout ? LAYOUT_TYPES : CHART_TYPES).includes(t.value)), panel.type, (v) => ctx.changeType(panel, v))),
      ...(layout ? layoutOptions(panel) : chartOptions(panel)),
      h('h3', { class: 'section-heading', text: 'Yerleşim' }),
      quickLayout(panel, model.smart.rows),
      h('div', { class: 'toolbar', style: { marginTop: '12px' } },
        button('Çoğalt', { icon: 'copy', size: 'sm', onClick: () => ctx.duplicate(panel) }),
        button('Sil', { icon: 'trash', size: 'sm', variant: 'danger', onClick: () => ctx.removePanel(panel) })),
    ];
  }

  return {
    el,
    render() {
      const model = ctx.getModel();
      const panel = model.panels.find((p) => p.id === ctx.getSelected());
      clear(el).append(...(panel ? panelSettings(model, panel) : pageSettings(model)).filter(Boolean));
    },
  };
}

export { icon };
