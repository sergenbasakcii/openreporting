// Full-screen panel editor: live preview, queries/transformations tabs, visualization options pane.
import { h, button, input, select, textarea, field, toggle, segmented, section, tabs, clear, debounce, confirmDialog } from '../dom.js';
import { icon } from '../icons.js';
import { PLUGINS, ORDER, plugin, getPath, setPathImmutable, withDefaults, CALC_OPTIONS } from '../panels/registry.js';
import { PanelView } from './panelview.js';
import { queriesTab, transformationsTab } from '../query/editors.js';
import { unitOptions } from '../units.js';
import { NAMED, color } from '../colors.js';
import { timePicker } from '../time.js';

const COLOR_CHOICES = ['green', 'yellow', 'orange', 'red', 'blue', 'purple', 'dark-green', 'dark-red', 'semi-dark-orange', 'text'];

function toHex(c) { const v = color(c); return /^#[0-9a-f]{6}$/i.test(v) ? v : '#73bf69'; }

function thresholdsEditor(panel, onChange) {
  const wrap = h('div');
  const draw = () => {
    clear(wrap);
    const t = getPath(panel, 'fieldConfig.defaults.thresholds') || { mode: 'absolute', steps: [{ color: 'green', value: null }] };
    const steps = [...t.steps].sort((a, b) => (a.value ?? -Infinity) - (b.value ?? -Infinity));
    const commit = (next) => { Object.assign(panel, setPathImmutable(panel, 'fieldConfig.defaults.thresholds', next)); onChange(); draw(); };
    wrap.append(button('Eşik ekle', { icon: 'plus', size: 'sm', onClick: () => commit({ ...t, steps: [...steps, { color: 'red', value: (Number(steps[steps.length - 1].value) || 0) + 10 }] }) }));
    [...steps].reverse().forEach((step) => {
      const idx = steps.indexOf(step);
      const colorIn = h('input', { type: 'color', value: toHex(step.color), title: step.color, onchange: (e) => { steps[idx] = { ...step, color: e.target.value }; commit({ ...t, steps }); } });
      const named = select([{ value: '', label: 'Renk' }, ...COLOR_CHOICES.map((c) => ({ value: c, label: c }))], NAMED[step.color] ? step.color : '', (v) => { if (v) { steps[idx] = { ...step, color: v }; commit({ ...t, steps }); } });
      named.style.width = '110px';
      const valueEl = step.value === null || step.value === undefined ? h('span', { class: 'input', style: { display: 'flex', alignItems: 'center' }, text: 'Taban' })
        : input({ type: 'number', value: step.value, onChange: (e) => { steps[idx] = { ...step, value: Number(e.target.value) }; commit({ ...t, steps }); } });
      wrap.append(h('div', { class: 'threshold-row' }, colorIn, named, valueEl,
        step.value === null || step.value === undefined ? null : button('', { icon: 'trash', variant: 'ghost', size: 'sm', onClick: () => { steps.splice(idx, 1); commit({ ...t, steps }); } })));
    });
    wrap.append(field('Eşik modu', segmented([{ value: 'absolute', label: 'Mutlak' }, { value: 'percentage', label: 'Yüzde' }], t.mode || 'absolute', (v) => commit({ ...t, mode: v }))));
  };
  draw();
  return wrap;
}

function mappingsEditor(panel, onChange) {
  const wrap = h('div');
  const draw = () => {
    clear(wrap);
    const list = getPath(panel, 'fieldConfig.defaults.mappings') || [];
    const commit = (next) => { Object.assign(panel, setPathImmutable(panel, 'fieldConfig.defaults.mappings', next)); onChange(); draw(); };
    list.forEach((m, i) => {
      if (m.type === 'value') {
        for (const [val, res] of Object.entries(m.options || {})) {
          wrap.append(h('div', { class: 'threshold-row' }, h('span', { class: 'badge', text: 'değer' }),
            input({ value: val, onChange: (e) => { const o = { ...m.options }; delete o[val]; o[e.target.value] = res; list[i] = { ...m, options: o }; commit(list); } }),
            input({ value: res.text || '', placeholder: 'Gösterilecek metin', onChange: (e) => { list[i] = { ...m, options: { ...m.options, [val]: { ...res, text: e.target.value } } }; commit(list); } }),
            h('input', { type: 'color', value: toHex(res.color || 'green'), onchange: (e) => { list[i] = { ...m, options: { ...m.options, [val]: { ...res, color: e.target.value } } }; commit(list); } }),
            button('', { icon: 'trash', variant: 'ghost', size: 'sm', onClick: () => { list.splice(i, 1); commit(list); } })));
        }
      } else if (m.type === 'range') {
        const o = m.options || {};
        wrap.append(h('div', { class: 'threshold-row' }, h('span', { class: 'badge', text: 'aralık' }),
          input({ type: 'number', value: o.from ?? '', placeholder: 'min', onChange: (e) => { list[i] = { ...m, options: { ...o, from: e.target.value === '' ? null : Number(e.target.value) } }; commit(list); } }),
          input({ type: 'number', value: o.to ?? '', placeholder: 'max', onChange: (e) => { list[i] = { ...m, options: { ...o, to: e.target.value === '' ? null : Number(e.target.value) } }; commit(list); } }),
          input({ value: o.result?.text || '', placeholder: 'Metin', onChange: (e) => { list[i] = { ...m, options: { ...o, result: { ...(o.result || {}), text: e.target.value } } }; commit(list); } }),
          h('input', { type: 'color', value: toHex(o.result?.color || 'green'), onchange: (e) => { list[i] = { ...m, options: { ...o, result: { ...(o.result || {}), color: e.target.value } } }; commit(list); } }),
          button('', { icon: 'trash', variant: 'ghost', size: 'sm', onClick: () => { list.splice(i, 1); commit(list); } })));
      }
    });
    wrap.append(h('div', { class: 'toolbar' }, button('Değer eşlemesi', { icon: 'plus', size: 'sm', onClick: () => commit([...list, { type: 'value', options: { 1: { text: 'UP', color: 'green' } } }]) }),
      button('Aralık eşlemesi', { icon: 'plus', size: 'sm', onClick: () => commit([...list, { type: 'range', options: { from: 0, to: 0, result: { text: 'DOWN', color: 'red' } } }]) })));
  };
  draw();
  return wrap;
}

function overridesEditor(panel, onChange) {
  const wrap = h('div');
  const PROPS = [{ value: 'displayName', label: 'Görünen ad' }, { value: 'unit', label: 'Birim' }, { value: 'color', label: 'Sabit renk' },
    { value: 'custom.axisPlacement', label: 'Eksen (left/right)' }, { value: 'custom.transform', label: 'Negatif Y (giden trafik)' },
    { value: 'custom.fillOpacity', label: 'Dolgu opaklığı' }, { value: 'custom.drawStyle', label: 'Stil (line/bars/points)' },
    { value: 'decimals', label: 'Ondalık' }, { value: 'min', label: 'Min' }, { value: 'max', label: 'Max' }, { value: 'custom.hidden', label: 'Tabloda gizle' }];
  const draw = () => {
    clear(wrap);
    const list = getPath(panel, 'fieldConfig.overrides') || [];
    const commit = (next) => { Object.assign(panel, setPathImmutable(panel, 'fieldConfig.overrides', next)); onChange(); draw(); };
    list.forEach((ov, i) => {
      const box = h('div', { class: 'query-row' });
      box.append(h('div', { class: 'q-head' }, select([{ value: 'byName', label: 'Ada göre' }, { value: 'byRegexp', label: 'Regex' }, { value: 'byFrameRefID', label: 'Sorguya göre' }], ov.matcher.id,
        (v) => { list[i] = { ...ov, matcher: { ...ov.matcher, id: v } }; commit(list); }),
      input({ value: ov.matcher.options || '', placeholder: 'seri adı / /regex/ / A', onChange: (e) => { list[i] = { ...ov, matcher: { ...ov.matcher, options: e.target.value } }; commit(list); } }),
      button('', { icon: 'trash', variant: 'ghost', size: 'sm', onClick: () => { list.splice(i, 1); commit(list); } })));
      const body = h('div', { class: 'q-body' });
      (ov.properties || []).forEach((p, pi) => {
        let ctl;
        if (p.id === 'color') ctl = h('input', { type: 'color', value: toHex(p.value?.fixedColor || 'green'), onchange: (e) => { ov.properties[pi] = { id: 'color', value: { mode: 'fixed', fixedColor: e.target.value } }; commit(list); } });
        else if (p.id === 'unit') ctl = select(unitOptions(), p.value || 'auto', (v) => { ov.properties[pi] = { ...p, value: v }; commit(list); });
        else if (p.id === 'custom.transform') ctl = select([{ value: 'negative-Y', label: 'Negatif Y' }, { value: 'constant', label: 'Yok' }], p.value || 'negative-Y', (v) => { ov.properties[pi] = { ...p, value: v }; commit(list); });
        else if (p.id === 'custom.hidden') ctl = toggle('', !!p.value, (v) => { ov.properties[pi] = { ...p, value: v }; commit(list); });
        else ctl = input({ value: p.value ?? '', onChange: (e) => { const raw = e.target.value; ov.properties[pi] = { ...p, value: ['decimals', 'min', 'max', 'custom.fillOpacity'].includes(p.id) && raw !== '' ? Number(raw) : raw }; commit(list); } });
        body.append(h('div', { class: 'threshold-row' }, h('span', { class: 'badge', text: (PROPS.find((x) => x.value === p.id) || { label: p.id }).label }), ctl,
          button('', { icon: 'close', variant: 'ghost', size: 'sm', onClick: () => { ov.properties.splice(pi, 1); commit(list); } })));
      });
      body.append(select([{ value: '', label: '+ Özellik ekle' }, ...PROPS], '', (v) => {
        if (!v) return;
        const defaults = { color: { mode: 'fixed', fixedColor: '#5794F2' }, unit: 'auto', 'custom.transform': 'negative-Y', 'custom.axisPlacement': 'right', 'custom.hidden': true };
        ov.properties = [...(ov.properties || []), { id: v, value: defaults[v] ?? '' }];
        commit(list);
      }));
      box.append(body);
      wrap.append(box);
    });
    wrap.append(button('Geçersiz kılma ekle', { icon: 'plus', size: 'sm', onClick: () => commit([...list, { matcher: { id: 'byName', options: '' }, properties: [] }]) }));
  };
  draw();
  return wrap;
}

function optionControl(panel, item, onChange) {
  const value = getPath(panel, item.path) ?? item.default;
  const set = (v) => { Object.assign(panel, setPathImmutable(panel, item.path, v)); onChange(); };
  switch (item.type) {
    case 'switch': return field(null, toggle(item.label, !!value, set));
    case 'radio': return field(item.label, segmented(item.options, value, set));
    case 'select': return field(item.label, select(item.options, value, set));
    case 'number': return field(item.label, input({ type: 'number', value: value ?? '', min: item.min, max: item.max, onChange: (e) => set(e.target.value === '' ? null : Number(e.target.value)) }));
    case 'textarea': return field(item.label, textarea({ value: value || '', rows: 10, class: 'code-editor', onInput: (e) => set(e.target.value) }));
    case 'calc': return field(item.label, select(CALC_OPTIONS, (value && value[0]) || 'lastNotNull', (v) => set([v])));
    case 'multicalc': case 'multi': {
      const opts = item.type === 'multi' ? item.options : CALC_OPTIONS;
      const current = new Set(value || []);
      const box = h('div', { class: 'chips' });
      for (const o of opts) {
        box.append(h('label', { class: 'chip', style: { cursor: 'pointer' } }, h('input', { type: 'checkbox', checked: current.has(o.value), onchange: (e) => {
          if (e.target.checked) current.add(o.value); else current.delete(o.value);
          set([...current]);
        } }), o.label));
      }
      return field(item.label, box);
    }
    default: return field(item.label, input({ value: value ?? '', onChange: (e) => set(e.target.value) }));
  }
}

export function openPanelEditor({ panel, dashboard, ctx, variablesList, onApply, onSave, onCancel }) {
  const work = JSON.parse(JSON.stringify(panel));
  let dirty = false;
  let closed = false;
  const shell = h('div', { class: 'editor-shell', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Panel düzenleyici' });
  const close = () => {
    if (closed) return;
    closed = true;
    view.destroy(); shell.remove(); document.removeEventListener('keydown', onKey, true);
  };
  const onKey = (e) => { if (e.key === 'Escape' && !document.querySelector('.modal-backdrop, .menu')) { e.preventDefault(); apply(); } };
  const apply = () => { if (closed) return; close(); onApply(work); };
  const discard = async () => {
    if (dirty && !(await confirmDialog('Değişiklikler atılsın mı?', 'Panelde kaydedilmemiş değişiklikler var.', { okText: 'At', danger: true }))) return;
    if (closed) return;
    close();
    if (onCancel) onCancel();
  };
  const titleEl = h('h3', { text: `Panel düzenle · ${work.title || ''}` });
  shell.append(h('div', { class: 'editor-top' }, button('', { icon: 'arrow-up', variant: 'ghost', title: 'Dashboard’a dön', onClick: apply }), titleEl,
    button('Vazgeç', { onClick: discard }), button('Uygula', { onClick: apply }), onSave ? button('Kaydet', { icon: 'save', variant: 'primary', onClick: () => { apply(); onSave(); } }) : null));
  const previewBox = h('div', { class: 'preview-box' });
  const viewCtx = { ...ctx, editable: false };
  const view = new PanelView(work, viewCtx, {});
  previewBox.append(view.el);
  // Debounced callbacks can fire after the editor closed; the destroyed preview must not be touched then.
  const refresh = debounce(() => { if (!closed) view.refresh(); }, 350);
  const rerender = debounce(() => { if (!closed) { view.updateTitle(); view.render(); } }, 60);
  const changedQuery = () => { dirty = true; refresh(); updateTabs(); };
  const changedOptions = () => { dirty = true; titleEl.textContent = `Panel düzenle · ${work.title || ''}`; rerender(); };
  const tp = timePicker({ range: ctx.range, timezone: ctx.timezone, compact: true, onChange: (r) => { view.setContext({ range: r, now: Date.now() }); tp.setRange(r); view.refresh(); } });
  const preview = h('div', { class: 'editor-preview' }, h('div', { class: 'preview-bar' }, h('span', { class: 'spacer' }), tp, button('', { icon: 'refresh', title: 'Yenile', onClick: () => view.refresh() })), previewBox);
  const bottom = h('div', { class: 'editor-bottom' });
  const splitter = h('div', { class: 'editor-splitter', title: 'Sürükleyerek boyutlandır' });
  splitter.addEventListener('pointerdown', (e) => {
    const startY = e.clientY; const startH = preview.getBoundingClientRect().height;
    const move = (ev) => { preview.style.flex = `0 0 ${Math.max(140, Math.min(window.innerHeight - 200, startH + ev.clientY - startY))}px`; };
    const up = () => { document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', up); view.viz && view.viz.resize && view.viz.resize(); };
    document.addEventListener('pointermove', move); document.addEventListener('pointerup', up);
  });
  const tabHost = h('div');
  const tabContent = h('div');
  let activeTab = 'queries';
  const updateTabs = () => {
    clear(tabHost);
    tabHost.append(tabs([{ id: 'queries', label: 'Sorgular', count: (work.targets || []).length }, { id: 'transform', label: 'Dönüşümler', count: (work.transformations || []).length }],
      activeTab, (id) => { activeTab = id; showTab(); }));
  };
  const showTab = () => {
    clear(tabContent);
    if (plugin(work.type).noQueries) { tabContent.append(h('p', { class: 'muted', text: 'Bu görselleştirme sorgu kullanmaz.' })); return; }
    tabContent.append(activeTab === 'queries' ? queriesTab(work, ctx, changedQuery) : transformationsTab(work, changedQuery));
  };
  updateTabs(); showTab();
  bottom.append(tabHost, tabContent);
  const left = h('div', { class: 'editor-left' }, preview, splitter, bottom);
  const right = h('div', { class: 'editor-right' });
  const drawOptions = (filter = '') => {
    clear(right);
    const search = input({ placeholder: 'Seçeneklerde ara…', value: filter, onInput: debounce((e) => drawOptions(e.target.value), 250) });
    right.append(h('div', { class: 'opt-search' }, search));
    const picker = h('div', { class: 'viz-picker' }, ORDER.map((type) => h('button', { type: 'button', class: work.type === type ? 'on' : '', onclick: () => {
      const prevTargets = work.targets;
      const next = withDefaults({ ...work, type, options: {}, fieldConfig: { defaults: { ...(work.fieldConfig?.defaults || {}), custom: undefined }, overrides: work.fieldConfig?.overrides || [] } });
      Object.keys(work).forEach((k) => delete work[k]);
      Object.assign(work, next, { targets: PLUGINS[type].noQueries ? prevTargets : (prevTargets && prevTargets.length ? prevTargets : [{ refId: 'A' }]) });
      dirty = true; drawOptions(); showTab(); view.refresh();
    } }, icon(PLUGINS[type].icon), PLUGINS[type].name)));
    right.append(section('Görselleştirme', picker));
    const f = filter.toLowerCase();
    const matches = (label) => !f || String(label).toLowerCase().includes(f);
    const panelOpts = [
      matches('Başlık') && field('Başlık', input({ value: work.title || '', onInput: (e) => { work.title = e.target.value; changedOptions(); } })),
      matches('Açıklama') && field('Açıklama', textarea({ value: work.description || '', rows: 2, onInput: (e) => { work.description = e.target.value; changedOptions(); } })),
      matches('Şeffaf') && field(null, toggle('Şeffaf arka plan', !!work.transparent, (v) => { work.transparent = v; changedOptions(); })),
      matches('Tekrarla') && field('Değişkene göre tekrarla', select([{ value: '', label: 'Kapalı' }, ...variablesList.map((v) => ({ value: v, label: `$${v}` }))], work.repeat || '', (v) => { work.repeat = v || undefined; changedOptions(); }),
        'Örn. $host seçilirse her host için bir panel oluşturulur (grup raporları için).'),
      work.repeat && field('Tekrar yönü', segmented([{ value: 'h', label: 'Yatay' }, { value: 'v', label: 'Dikey' }], work.repeatDirection || 'h', (v) => { work.repeatDirection = v; changedOptions(); })),
      work.repeat && field('Satır başına en fazla', select(['', '2', '3', '4', '6', '8', '12'].map((x) => ({ value: x, label: x || 'Otomatik' })), String(work.maxPerRow || ''), (v) => { work.maxPerRow = v ? Number(v) : undefined; changedOptions(); })),
    ].filter(Boolean);
    right.append(section('Panel seçenekleri', panelOpts));
    for (const sec of plugin(work.type).sections || []) {
      const items = sec.items.filter((it) => matches(it.label) || matches(sec.title)).map((it) => optionControl(work, it, changedOptions));
      if (items.length) right.append(section(sec.title, items));
    }
    if (!plugin(work.type).noQueries) {
      const d = work.fieldConfig?.defaults || {};
      const setD = (key, v) => { Object.assign(work, setPathImmutable(work, `fieldConfig.defaults.${key}`, v)); changedOptions(); };
      right.append(section('Standart seçenekler', [
        field('Birim', select(unitOptions(), d.unit || 'auto', (v) => setD('unit', v))),
        h('div', { class: 'inline-fields' }, field('Min', input({ type: 'number', value: d.min ?? '', placeholder: 'otomatik', onChange: (e) => setD('min', e.target.value === '' ? undefined : Number(e.target.value)) })),
          field('Max', input({ type: 'number', value: d.max ?? '', placeholder: 'otomatik', onChange: (e) => setD('max', e.target.value === '' ? undefined : Number(e.target.value)) })),
          field('Ondalık', input({ type: 'number', value: d.decimals ?? '', placeholder: 'otomatik', min: 0, max: 10, onChange: (e) => setD('decimals', e.target.value === '' ? undefined : Number(e.target.value)) }))),
        field('Görünen ad', input({ value: d.displayName || '', placeholder: '${__field.name}', onChange: (e) => setD('displayName', e.target.value || undefined) })),
        field('Renk şeması', select([{ value: 'palette-classic', label: 'Klasik palet' }, { value: 'thresholds', label: 'Eşiklerden' }, { value: 'fixed', label: 'Tek renk' }],
          d.color?.mode || 'palette-classic', (v) => setD('color', { ...(d.color || {}), mode: v }))),
        d.color?.mode === 'fixed' ? field('Renk', h('input', { type: 'color', value: toHex(d.color.fixedColor || 'green'), onchange: (e) => setD('color', { mode: 'fixed', fixedColor: e.target.value }) })) : null,
        field('Veri yok metni', input({ value: d.noValue || '', placeholder: 'Veri yok', onChange: (e) => setD('noValue', e.target.value || undefined) })),
      ]));
      if (plugin(work.type).thresholds) right.append(section('Eşikler', thresholdsEditor(work, changedOptions)));
      right.append(section('Değer eşlemeleri', mappingsEditor(work, changedOptions), { open: false }));
      right.append(section('Geçersiz kılmalar (overrides)', overridesEditor(work, changedOptions), { open: false }));
    }
  };
  drawOptions();
  shell.append(h('div', { class: 'editor-main' }, left, right));
  document.getElementById('overlay-root').append(shell);
  document.addEventListener('keydown', onKey, true);
  view.refresh();
  return { close };
}

export { icon };
