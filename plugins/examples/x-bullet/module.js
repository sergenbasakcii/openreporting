// Example panel plugin: "bullet" bars — each series' last value against a target and a warning level.
// Copy this folder to <data dir>/plugins/x-bullet and add x-bullet to OPENREPORTING_PLUGINS.
// Contract: export register(api); api.registerPanel(id, { name, icon, defaults, sections, render }).

function lastValue(frame) {
  if (frame.type === 'timeseries') {
    for (let i = frame.points.length - 1; i >= 0; i -= 1) if (frame.points[i][1] !== null) return frame.points[i][1];
    return null;
  }
  const row = frame.rows?.[0];
  return row ? row.find((v) => typeof v === 'number') ?? null : null;
}

export function register(api) {
  const { h, clear } = api.dom;
  api.registerPanel('x-bullet', {
    name: 'Hedef çubuğu (eklenti)',
    icon: 'gauge',
    defaults: { options: { target: 100, warning: 80 } },
    sections: [{
      title: 'Hedef',
      items: [
        { path: 'options.target', label: 'Hedef (%100 noktası)', type: 'number', default: 100 },
        { path: 'options.warning', label: 'Uyarı seviyesi', type: 'number', default: 80 },
      ],
    }],
    render(container, frames, panel) {
      clear(container);
      const target = Number(panel.options?.target) || 100;
      const warning = Number(panel.options?.warning) || target * 0.8;
      const list = h('div', { class: 'x-bullet' });
      for (const frame of frames) {
        const value = lastValue(frame);
        const ratio = value === null ? 0 : Math.max(0, Math.min(1, value / target));
        const state = value === null ? 'none' : value >= target ? 'crit' : value >= warning ? 'warn' : 'ok';
        list.append(h('div', { class: 'x-bullet-row', title: `${frame.name}: ${value ?? 'veri yok'}` },
          h('span', { class: 'x-bullet-name', text: frame.name }),
          h('span', { class: 'x-bullet-track' }, h('span', { class: `x-bullet-fill x-bullet-${state}`, style: { width: `${ratio * 100}%` } })),
          h('span', { class: 'x-bullet-value', text: value === null ? '—' : String(Math.round(value * 100) / 100) })));
      }
      if (!frames.length) list.append(h('p', { class: 'muted', text: 'Veri yok' }));
      container.append(list);
    },
  });
}
