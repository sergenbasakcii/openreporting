// Query editors (Zabbix / TestData / PostgreSQL / Expression), function chips, transformations.
import { h, button, input, select, textarea, field, toggle, menu, clear, debounce } from '../dom.js';
import { icon } from '../icons.js';
import { post, datasourcesList, queryCatalog, cached } from '../api.js';
import { effectiveZone } from '../time.js';

export const EXPR = { type: '__expr__', uid: '__expr__' };
const QUERY_TYPES = [{ value: 'metrics', label: 'Metrikler' }, { value: 'itemvalues', label: 'Son değerler (tablo)' },
  { value: 'itemid', label: 'Item ID' }, { value: 'problems', label: 'Aktif problemler' }];
const SCENARIOS = [{ value: 'zabbix_sim', label: 'Zabbix simülasyonu' }, { value: 'random_walk', label: 'Rastgele yürüyüş' },
  { value: 'sine', label: 'Sinüs dalgası' }, { value: 'csv_values', label: 'CSV değerleri' }, { value: 'table_static', label: 'Örnek tablo' }];

let datalistSeq = 0;

function suggestInput(value, onChange, loader, placeholder, variables) {
  const listId = `dl-${datalistSeq += 1}`;
  const list = h('datalist', { id: listId });
  const el = input({ value: value || '', placeholder, list: listId, onChange: (e) => onChange(e.target.value) });
  let loaded = false;
  el.addEventListener('focus', async () => {
    if (loaded) return;
    loaded = true;
    try {
      const values = await loader();
      const vars = Object.keys(variables || {}).map((n) => `$${n}`);
      clear(list);
      for (const v of [...vars, '/.*/', ...values.slice(0, 2000)]) list.append(h('option', { value: v }));
    } catch { loaded = false; }
  });
  return [el, list];
}

function metricFind(dsUid, query, ctx) {
  const key = `mf:${dsUid}:${JSON.stringify(query)}:${JSON.stringify(ctx.variables || {})}`;
  return cached(key, async () => {
    const res = await post(`/api/datasources/${encodeURIComponent(dsUid)}/metric-find`, { query, range: ctx.range || { from: 'now-6h', to: 'now' },
      timezone: effectiveZone(ctx.timezone), variables: ctx.variables || {} });
    return res.values.map((v) => v.text);
  }, 60000);
}

function zabbixEditor(target, ds, ctx, onChange) {
  const t = { ...target };
  const set = (patch) => { Object.assign(t, patch); onChange({ ...t }); };
  const filter = (key) => (typeof t[key] === 'object' && t[key] ? t[key].filter : t[key]) || '';
  const wrap = h('div');
  const qType = { '0': 'metrics', '2': 'itemvalues', '3': 'itemid', '4': 'problems', '5': 'problems' }[String(t.queryType)] || t.queryType || 'metrics';
  const line1 = h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Sorgu türü' }),
    select(QUERY_TYPES, qType, (v) => { set({ queryType: v }); rerender(); }, { class: 'auto-width' }));
  if (ds.type === 'testdata') {
    line1.prepend(h('span', { class: 'q-label', text: 'Senaryo' }), select(SCENARIOS, t.scenario || 'zabbix_sim', (v) => { set({ scenario: v }); rerender(); }));
  }
  wrap.append(line1);
  const rerender = () => { const fresh = queryEditor(t, ds, ctx, onChange); wrap.replaceWith(fresh); };
  if (ds.type === 'testdata' && t.scenario && t.scenario !== 'zabbix_sim') {
    line1.lastChild.remove(); line1.lastChild.remove();
    const s = t.scenario;
    const row = h('div', { class: 'q-line' });
    if (s === 'random_walk' || s === 'sine') row.append(h('span', { class: 'q-label', text: 'Seri sayısı' }), input({ type: 'number', value: t.seriesCount || 1, min: 1, max: 50, onChange: (e) => set({ seriesCount: Number(e.target.value) }) }));
    if (s === 'random_walk') row.append(h('span', { class: 'q-label', text: 'Min' }), input({ type: 'number', value: t.min ?? 0, onChange: (e) => set({ min: Number(e.target.value) }) }),
      h('span', { class: 'q-label', text: 'Max' }), input({ type: 'number', value: t.max ?? 100, onChange: (e) => set({ max: Number(e.target.value) }) }));
    if (s === 'sine') row.append(h('span', { class: 'q-label', text: 'Genlik' }), input({ type: 'number', value: t.amplitude ?? 10, onChange: (e) => set({ amplitude: Number(e.target.value) }) }),
      h('span', { class: 'q-label', text: 'Periyot' }), input({ value: t.period || '1h', onChange: (e) => set({ period: e.target.value }) }));
    if (s === 'csv_values') row.append(h('span', { class: 'q-label', text: 'Değerler' }), input({ value: t.csvValues || '1,20,90,30,5,0', onChange: (e) => set({ csvValues: e.target.value }) }));
    row.append(h('span', { class: 'q-label', text: 'Takma ad' }), input({ value: t.alias || '', placeholder: 'seri-$seriesIndex', onChange: (e) => set({ alias: e.target.value }) }));
    wrap.append(row, functionsEditor(t.functions || [], (functions) => set({ functions })));
    return wrap;
  }
  if (qType === 'itemid') {
    wrap.append(h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Item ID' }),
      input({ value: t.itemids || '', placeholder: '12345,67890', onChange: (e) => set({ itemids: e.target.value }) })));
  } else {
    const uid = ds.uid;
    const grp = suggestInput(filter('group'), (v) => set({ group: { filter: v } }), () => metricFind(uid, { type: 'group' }, ctx), 'Grup (regex: /Linux.*/)', ctx.variables);
    const host = suggestInput(filter('host'), (v) => set({ host: { filter: v } }), () => metricFind(uid, { type: 'host', group: filter('group') }, ctx), 'Host (/.*/ = tümü)', ctx.variables);
    wrap.append(h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Grup' }), ...grp, h('span', { class: 'q-label', text: 'Host' }), ...host));
    if (qType !== 'problems') {
      const tag = suggestInput(filter('itemTag'), (v) => set({ itemTag: { filter: v } }), () => metricFind(uid, { type: 'itemTag', group: filter('group'), host: filter('host') }, ctx), 'Etiket (ör. component: cpu)', ctx.variables);
      const item = suggestInput(filter('item'), (v) => set({ item: { filter: v } }), () => metricFind(uid, { type: 'item', group: filter('group'), host: filter('host'), itemTag: filter('itemTag') }, ctx), 'Item adı (regex: /CPU/)', ctx.variables);
      wrap.append(h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Etiket' }), ...tag, h('span', { class: 'q-label', text: 'Item' }), ...item));
    } else {
      wrap.append(h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Problem metni' }),
        input({ value: (t.trigger && t.trigger.filter) || '', placeholder: '/.*/', onChange: (e) => set({ trigger: { filter: e.target.value } }) }),
        h('span', { class: 'q-label', text: 'En düşük önem' }),
        select([0, 1, 2, 3, 4, 5].map((v) => ({ value: String(v), label: ['Sınıflandırılmamış', 'Bilgi', 'Uyarı', 'Ortalama', 'Yüksek', 'Felaket'][v] })),
          String((t.options && t.options.minSeverity) || 0), (v) => set({ options: { ...(t.options || {}), minSeverity: Number(v) } }))));
    }
  }
  if (qType === 'metrics' || qType === 'itemid') {
    const opts = t.options || {};
    wrap.append(functionsEditor(t.functions || [], (functions) => set({ functions })));
    wrap.append(h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Veri' }),
      select([{ value: 'auto', label: 'Otomatik (history / trend)' }, { value: 'history', label: 'Ham history' }, { value: 'trends', label: 'Trend (saatlik)' }],
        opts.mode || (opts.useTrends === 'true' ? 'trends' : opts.useTrends === 'false' ? 'history' : 'auto'), (v) => set({ options: { ...opts, mode: v, useTrends: undefined } })),
      toggle('Devre dışı item’ları göster', !!opts.showDisabledItems, (v) => set({ options: { ...opts, showDisabledItems: v } }))));
  }
  return wrap;
}

function postgresEditor(target, ds, ctx, onChange) {
  const t = { ...target };
  const set = (patch) => { Object.assign(t, patch); onChange({ ...t }); };
  const sql = textarea({ value: t.rawSql || "SELECT\n  $__unixEpochGroupAlias(clock, $__interval),\n  avg(value) AS \"değer\"\nFROM history\nWHERE itemid = 12345 AND $__unixEpochFilter(clock)\nGROUP BY 1\nORDER BY 1",
    rows: 8, class: 'code-editor', onChange: (e) => set({ rawSql: e.target.value }) });
  if (!t.rawSql) setTimeout(() => set({ rawSql: sql.value }), 0);
  return h('div', h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Biçim' }),
    select([{ value: 'time_series', label: 'Zaman serisi' }, { value: 'table', label: 'Tablo' }], t.format || 'time_series', (v) => set({ format: v }))), sql,
  h('p', { class: 'hint' }, 'Makrolar: $__timeFilter(ts), $__unixEpochFilter(clock), $__timeGroupAlias(ts, 5m), $__unixEpochGroupAlias(clock, $__interval), $__timeFrom(), $__timeTo(). ',
    'Zaman serisi için "time" sütunu, isteğe bağlı "metric" sütunu ve sayısal değer sütunları döndürün. Sorgular salt-okunur işlemde çalışır.'),
  functionsEditor(t.functions || [], (functions) => set({ functions })));
}

function expressionEditor(target, ctx, onChange) {
  const t = { ...target };
  const set = (patch) => { Object.assign(t, patch); onChange({ ...t }); };
  const type = t.type || 'math';
  const wrap = h('div');
  const rerender = () => wrap.replaceWith(expressionEditor(t, ctx, onChange));
  wrap.append(h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'İfade türü' }),
    select([{ value: 'math', label: 'Matematik' }, { value: 'reduce', label: 'Tek değere indir' }, { value: 'resample', label: 'Yeniden örnekle' }], type, (v) => { set({ type: v }); rerender(); })));
  if (type === 'math') {
    wrap.append(h('div', { class: 'q-line' }, input({ value: t.expression || '', placeholder: '$A / $B * 100', onChange: (e) => set({ expression: e.target.value }) })),
      h('p', { class: 'hint', text: 'Sorgulara $A, $B ile başvurun. +, -, *, /, %, **, karşılaştırmalar ve abs, log, sqrt, round, min, max kullanılabilir. Çok serili sorgular host etiketine göre eşleştirilir.' }));
  } else {
    wrap.append(h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Girdi' }), input({ value: t.expression || 'A', onChange: (e) => set({ expression: e.target.value }) })));
    if (type === 'reduce') {
      queryCatalog().then((c) => wrap.append(h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Hesaplama' }),
        select(c.reducers, t.reducer || 'mean', (v) => set({ reducer: v })))));
    } else {
      wrap.append(h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Pencere' }), input({ value: t.window || '5m', onChange: (e) => set({ window: e.target.value }) }),
        h('span', { class: 'q-label', text: 'Fonksiyon' }), select(['avg', 'min', 'max', 'sum', 'last'], t.downsampler || 'avg', (v) => set({ downsampler: v }))));
    }
  }
  return wrap;
}

export function queryEditor(target, ds, ctx, onChange) {
  if (!ds) return h('div', { class: 'alert warn', text: 'Veri kaynağı bulunamadı; bir veri kaynağı seçin.' });
  if (ds.type === '__expr__') return expressionEditor(target, ctx, onChange);
  if (ds.type === 'postgres') return postgresEditor(target, ds, ctx, onChange);
  return zabbixEditor(target, ds, ctx, onChange);
}

export function functionsEditor(functions, onChange) {
  const wrap = h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Fonksiyonlar' }));
  const list = functions.map((f) => ({ name: f.name || (f.def && f.def.name) || f.def, params: [...(f.params || [])] }));
  const emit = () => onChange(list.map((f) => ({ name: f.name, params: f.params })));
  queryCatalog().then((catalog) => {
    const byName = Object.fromEntries(catalog.functions.map((f) => [f.name, f]));
    const draw = () => {
      while (wrap.childNodes.length > 1) wrap.lastChild.remove();
      list.forEach((fn, index) => {
        const spec = byName[fn.name] || { params: [] };
        const chip = h('span', { class: 'fn-chip', title: spec.description || '' }, h('b', { text: fn.name }), '(');
        spec.params.forEach((p, pi) => {
          const value = fn.params[pi] ?? p.default;
          let ctl;
          if (p.type === 'agg') ctl = h('select', { onchange: (e) => { fn.params[pi] = e.target.value; emit(); } }, ['avg', 'min', 'max', 'sum', 'count', 'median', 'first', 'last'].map((o) => h('option', { value: o, text: o, selected: o === value })));
          else if (p.type === 'reducer') ctl = h('select', { onchange: (e) => { fn.params[pi] = e.target.value; emit(); } }, catalog.reducers.map((o) => h('option', { value: o.value, text: o.value, selected: o.value === value })));
          else if (p.type === 'order') ctl = h('select', { onchange: (e) => { fn.params[pi] = e.target.value; emit(); } }, ['desc', 'asc'].map((o) => h('option', { value: o, text: o, selected: o === value })));
          else if (p.type === 'trend') ctl = h('select', { onchange: (e) => { fn.params[pi] = e.target.value; emit(); } }, ['avg', 'min', 'max', 'sum', 'count'].map((o) => h('option', { value: o, text: o, selected: o === value })));
          else if (p.type === 'op') ctl = h('select', { onchange: (e) => { fn.params[pi] = e.target.value; emit(); } }, ['>', '>=', '<', '<=', '=', '!='].map((o) => h('option', { value: o, text: o, selected: o === value })));
          else ctl = h('input', { value: value ?? '', title: p.name, onchange: (e) => { fn.params[pi] = ['number', 'int'].includes(p.type) && e.target.value !== '' && !Number.isNaN(Number(e.target.value)) ? Number(e.target.value) : e.target.value; emit(); } });
          if (fn.params[pi] === undefined) fn.params[pi] = p.default;
          chip.append(ctl, pi < spec.params.length - 1 ? ', ' : '');
        });
        chip.append(')', h('button', { type: 'button', class: 'btn ghost sm icon', title: 'Sola taşı', onclick: () => { if (index > 0) { [list[index - 1], list[index]] = [list[index], list[index - 1]]; emit(); draw(); } } }, icon('chevron-left')),
          h('button', { type: 'button', class: 'btn ghost sm icon', title: 'Kaldır', onclick: () => { list.splice(index, 1); emit(); draw(); } }, icon('close')));
        wrap.append(chip);
      });
      const add = button('', { icon: 'plus', size: 'sm', title: 'Fonksiyon ekle', onClick: () => {
        const groups = {};
        for (const f of catalog.functions) (groups[f.category] = groups[f.category] || []).push(f);
        const items = [];
        for (const [cat, fns] of Object.entries(groups)) {
          items.push({ title: cat });
          for (const f of fns) items.push({ label: f.name, onClick: () => { list.push({ name: f.name, params: f.params.map((p) => p.default) }); emit(); draw(); } });
        }
        menu(add, items);
      } });
      wrap.append(add);
    };
    draw();
  });
  return wrap;
}

export async function dsByRef(ref) {
  const list = await datasourcesList();
  if (ref && (ref.type === '__expr__' || ref.uid === '__expr__')) return { ...EXPR, name: 'İfade' };
  const uid = ref && typeof ref === 'object' ? ref.uid : ref;
  return list.find((d) => d.uid === uid || d.name === uid) || list.find((d) => d.isDefault) || list[0] || null;
}

// The Queries tab: datasource picker, query rows, options.
export function queriesTab(panel, ctx, onChange) {
  const root = h('div');
  const draw = async () => {
    const list = await datasourcesList();
    clear(root);
    const panelDs = await dsByRef(panel.datasource);
    const mixed = panel.datasource && panel.datasource.uid === '-- Mixed --';
    const dsOptions = [...list.map((d) => ({ value: d.uid, label: `${d.name} (${d.type})` })), { value: '-- Mixed --', label: '— Karışık (sorgu başına) —' }];
    const opts = h('div', { class: 'inline-fields', style: { marginBottom: '12px' } },
      field('Veri kaynağı', select(dsOptions, mixed ? '-- Mixed --' : panelDs ? panelDs.uid : '', (uid) => {
        panel.datasource = { uid };
        if (uid !== '-- Mixed --') panel.targets = (panel.targets || []).map((t) => (t.datasource && t.datasource.type === '__expr__' ? t : { ...t, datasource: undefined }));
        onChange(); draw();
      })),
      field('En fazla nokta', input({ type: 'number', value: panel.maxDataPoints || '', placeholder: 'otomatik', onChange: (e) => { panel.maxDataPoints = e.target.value ? Number(e.target.value) : undefined; onChange(); } })),
      field('En küçük aralık', input({ value: panel.interval || '', placeholder: 'ör. 1m', onChange: (e) => { panel.interval = e.target.value || undefined; onChange(); } })),
      field('Göreli zaman', input({ value: panel.timeFrom || '', placeholder: 'ör. 1h', onChange: (e) => { panel.timeFrom = e.target.value || undefined; onChange(); } })),
      field('Zaman kaydırma', input({ value: panel.timeShift || '', placeholder: 'ör. 1d', onChange: (e) => { panel.timeShift = e.target.value || undefined; onChange(); } })));
    root.append(opts);
    const targets = panel.targets || (panel.targets = []);
    targets.forEach((target, index) => {
      const isExpr = target.datasource && (target.datasource.type === '__expr__' || target.datasource.uid === '__expr__');
      const row = h('div', { class: ['query-row', target.hide ? 'hidden-q' : ''].join(' ') });
      const body = h('div', { class: 'q-body' });
      const refInput = h('span', { class: 'ref', contenteditable: 'true', spellcheck: 'false', text: target.refId,
        onblur: (e) => { const v = e.target.textContent.trim().toUpperCase().replace(/[^A-Z0-9_]/g, ''); if (v && !targets.some((t, i) => i !== index && t.refId === v)) { target.refId = v; onChange(); } else e.target.textContent = target.refId; } });
      const head = h('div', { class: 'q-head' }, button('', { icon: 'chevron-down', variant: 'ghost', size: 'sm', onClick: () => row.classList.toggle('collapsed') }), refInput,
        isExpr ? h('span', { class: 'badge info', text: 'İfade' }) : null,
        !isExpr && mixed ? select(list.map((d) => ({ value: d.uid, label: d.name })), (target.datasource && target.datasource.uid) || (list[0] && list[0].uid), (uid) => { target.datasource = { uid }; onChange(); draw(); }) : null,
        h('span', { class: 'spacer' }),
        button('', { icon: target.hide ? 'eye-off' : 'eye', variant: 'ghost', size: 'sm', title: target.hide ? 'Göster' : 'Gizle (yalnızca ifadelerde kullan)', onClick: () => { target.hide = !target.hide; onChange(); draw(); } }),
        button('', { icon: 'copy', variant: 'ghost', size: 'sm', title: 'Çoğalt', onClick: () => { targets.splice(index + 1, 0, { ...JSON.parse(JSON.stringify(target)), refId: nextRef(targets) }); onChange(); draw(); } }),
        button('', { icon: 'trash', variant: 'ghost', size: 'sm', title: 'Sil', onClick: () => { targets.splice(index, 1); onChange(); draw(); } }));
      row.append(head, body);
      dsByRef(isExpr ? EXPR : (mixed ? target.datasource : panel.datasource)).then((ds) => {
        body.append(queryEditor(target, ds, ctx, (updated) => { targets[index] = updated; onChange(); }));
      });
      root.append(row);
    });
    root.append(h('div', { class: 'toolbar' },
      button('Sorgu ekle', { icon: 'plus', onClick: () => { targets.push({ refId: nextRef(targets) }); onChange(); draw(); } }),
      button('İfade ekle', { icon: 'function', onClick: () => { targets.push({ refId: nextRef(targets), datasource: { ...EXPR }, type: 'math', expression: '' }); onChange(); draw(); } })));
  };
  draw();
  return root;
}

export function nextRef(targets) {
  for (let i = 0; i < 26; i += 1) { const c = String.fromCharCode(65 + i); if (!targets.some((t) => t.refId === c)) return c; }
  return `Q${targets.length + 1}`;
}

// Transformations tab
export function transformationsTab(panel, onChange) {
  const root = h('div');
  const draw = async () => {
    const catalog = await queryCatalog();
    clear(root);
    const list = panel.transformations || (panel.transformations = []);
    root.append(h('p', { class: 'hint', text: 'Dönüşümler sunucuda sırayla uygulanır; dashboard ve PDF rapor aynı sonucu üretir.' }));
    list.forEach((tr, index) => {
      const spec = catalog.transformations.find((x) => x.id === tr.id) || { name: tr.id };
      const body = transformationOptions(tr, catalog, () => onChange());
      root.append(h('div', { class: 'query-row' }, h('div', { class: 'q-head' }, h('span', { class: 'ref', text: `${index + 1}` }), h('b', { text: spec.name }), h('span', { class: 'faint', text: spec.description || '' }), h('span', { class: 'spacer' }),
        button('', { icon: tr.disabled ? 'eye-off' : 'eye', variant: 'ghost', size: 'sm', title: tr.disabled ? 'Etkinleştir' : 'Devre dışı bırak', onClick: () => { tr.disabled = !tr.disabled; onChange(); draw(); } }),
        button('', { icon: 'arrow-up', variant: 'ghost', size: 'sm', title: 'Yukarı', onClick: () => { if (index > 0) { [list[index - 1], list[index]] = [list[index], list[index - 1]]; onChange(); draw(); } } }),
        button('', { icon: 'trash', variant: 'ghost', size: 'sm', title: 'Sil', onClick: () => { list.splice(index, 1); onChange(); draw(); } })), h('div', { class: 'q-body' }, body)));
    });
    const add = button('Dönüşüm ekle', { icon: 'plus', onClick: () => menu(add, catalog.transformations.map((t) => ({ label: t.name, onClick: () => { list.push({ id: t.id, options: defaultTransformOptions(t.id) }); onChange(); draw(); } }))) });
    root.append(add);
  };
  draw();
  return root;
}

function defaultTransformOptions(id) {
  return ({ reduce: { reducers: ['mean', 'max', 'lastNotNull'], labelsToFields: true }, reduceByLabel: { label: 'host', reducer: 'mean', columnBy: 'item' },
    sortBy: { sort: [{ field: '', desc: true }] }, limit: { limitField: 10 }, filterByName: { include: '', exclude: '' }, filterByRefId: { include: 'A' },
    organize: { excludeByName: {}, renameByName: {}, indexByName: {} }, calculateField: { mode: 'reduceRow', reduce: { reducer: 'sum' }, alias: 'Toplam' },
    renameByRegex: { regex: '(.*)', renamePattern: '$1' }, groupingToMatrix: { rowField: '', columnField: '', valueField: '' } })[id] || {};
}

function transformationOptions(tr, catalog, onChange) {
  const o = tr.options || (tr.options = {});
  const text = (label, key, placeholder) => field(label, input({ value: o[key] ?? '', placeholder, onChange: (e) => { o[key] = e.target.value; onChange(); } }));
  const reducerSelect = (value, cb) => select(catalog.reducers, value, cb);
  switch (tr.id) {
    case 'reduce': {
      const chips = h('div', { class: 'chips' });
      const drawChips = () => { clear(chips); for (const r of o.reducers || []) chips.append(h('span', { class: 'chip' }, r, h('button', { type: 'button', text: '×', onclick: () => { o.reducers = o.reducers.filter((x) => x !== r); onChange(); drawChips(); } }))); };
      drawChips();
      return h('div', { class: 'inline-fields' }, field('Hesaplamalar', h('div', chips, reducerSelect('', (v) => { if (v && !(o.reducers || []).includes(v)) { o.reducers = [...(o.reducers || []), v]; onChange(); drawChips(); } }))),
        field('Mod', select([{ value: 'seriesToRows', label: 'Seriler satırlara' }, { value: 'reduceFields', label: 'Serileri tek noktaya indir' }], o.mode || 'seriesToRows', (v) => { o.mode = v; onChange(); })),
        field('', toggle('Etiketleri sütun yap (host, item, grup)', o.labelsToFields !== false, (v) => { o.labelsToFields = v; onChange(); })));
    }
    case 'reduceByLabel':
      return h('div', { class: 'inline-fields' }, text('Satır etiketi', 'label', 'host'),
        field('Hesaplama', reducerSelect(o.reducer || 'mean', (v) => { o.reducer = v; onChange(); })),
        field('Sütunlar', select([{ value: 'item', label: 'Item adı' }, { value: 'name', label: 'Seri adı' }, { value: 'refId', label: 'Sorgu (A, B…)' }, { value: 'label:group', label: 'Grup etiketi' }], o.columnBy || 'item', (v) => { o.columnBy = v; onChange(); })));
    case 'sortBy': {
      const s = (o.sort && o.sort[0]) || (o.sort = [{ field: '', desc: true }])[0];
      return h('div', { class: 'inline-fields' }, field('Sütun adı', input({ value: s.field || '', onChange: (e) => { s.field = e.target.value; onChange(); } })),
        field('', toggle('Azalan', !!s.desc, (v) => { s.desc = v; onChange(); })));
    }
    case 'limit': return h('div', { class: 'inline-fields' }, field('Satır sayısı', input({ type: 'number', value: o.limitField ?? 10, onChange: (e) => { o.limitField = Number(e.target.value); onChange(); } })));
    case 'filterByName': case 'filterFieldsByName': return h('div', { class: 'inline-fields' }, text('Dahil et (regex)', 'include', '/CPU|Memory/'), text('Hariç tut (regex)', 'exclude', ''));
    case 'filterByRefId': return h('div', { class: 'inline-fields' }, text('Sorgular (regex)', 'include', 'A|B'));
    case 'calculateField':
      return h('div', { class: 'inline-fields' }, field('Mod', select([{ value: 'reduceRow', label: 'Satırı indirge' }, { value: 'binary', label: 'İkili işlem' }], o.mode || 'reduceRow', (v) => { o.mode = v; onChange(); })),
        o.mode === 'binary' ? [field('Sol sütun', input({ value: o.binary?.left || '', onChange: (e) => { o.binary = { ...(o.binary || {}), left: e.target.value }; onChange(); } })),
          field('İşlem', select(['+', '-', '*', '/'], o.binary?.operator || '+', (v) => { o.binary = { ...(o.binary || {}), operator: v }; onChange(); })),
          field('Sağ sütun / sayı', input({ value: o.binary?.right || '', onChange: (e) => { o.binary = { ...(o.binary || {}), right: e.target.value }; onChange(); } }))]
          : field('Hesaplama', reducerSelect(o.reduce?.reducer || 'sum', (v) => { o.reduce = { ...(o.reduce || {}), reducer: v }; onChange(); })),
        text('Yeni sütun adı', 'alias', 'Toplam'));
    case 'renameByRegex': return h('div', { class: 'inline-fields' }, text('Regex', 'regex', '(.*)'), text('Yeni ad', 'renamePattern', '$1'));
    case 'groupingToMatrix': return h('div', { class: 'inline-fields' }, text('Satır sütunu', 'rowField'), text('Kolon sütunu', 'columnField'), text('Değer sütunu', 'valueField'));
    case 'organize': {
      const rename = JSON.stringify(o.renameByName || {});
      const exclude = Object.keys(o.excludeByName || {}).join(', ');
      return h('div', { class: 'inline-fields' },
        field('Gizlenecek sütunlar (virgülle)', input({ value: exclude, onChange: (e) => { o.excludeByName = Object.fromEntries(e.target.value.split(',').map((x) => x.trim()).filter(Boolean).map((x) => [x, true])); onChange(); } })),
        field('Yeniden adlandır (JSON)', input({ value: rename, onChange: (e) => { try { o.renameByName = JSON.parse(e.target.value || '{}'); onChange(); } catch { e.target.classList.add('invalid'); } } })));
    }
    default: return h('p', { class: 'hint', text: 'Bu dönüşümün ayarı yok.' });
  }
}

export const debouncedChange = debounce((fn) => fn(), 400);
