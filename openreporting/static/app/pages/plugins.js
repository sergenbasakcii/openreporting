// Plugin status for administrators: allow-list, loaded / disabled / failed plugins.
import { h, loading, clear } from '../dom.js';
import { icon } from '../icons.js';
import { get } from '../api.js';
import { setBreadcrumbs } from '../router.js';
import { LOADED } from '../plugins.js';

const STATE = { loaded: ['ok', 'yüklendi'], disabled: ['', 'izin listesinde değil'], error: ['err', 'hata'] };
const KIND = { datasource: 'Veri kaynağı (sunucu)', panel: 'Panel (tarayıcı)' };

export async function pluginsPage(root) {
  setBreadcrumbs([{ label: 'Yönetim' }, { label: 'Eklentiler' }]);
  const page = h('div', { class: 'page' }, loading());
  root.append(page);
  const data = await get('/api/admin/plugins');
  const inBrowser = new Set(LOADED.map((p) => p.id));
  clear(page).append(
    h('div', { class: 'page-header' }, h('div', h('h1', icon('layers'), 'Eklentiler'),
      h('p', { class: 'sub', text: 'Veri kaynağı eklentileri sunucudaki Python ortamına kurulur; panel eklentileri eklenti klasörüne kopyalanır. Yalnız OPENREPORTING_PLUGINS listesindekiler yüklenir.' }))),
    h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'İzin listesi' }),
      h('p', { class: 'mono', text: data.enabled.length ? data.enabled.join(', ') : '(boş — hiçbir eklenti yüklenmez)' }),
      h('p', { class: 'hint', text: 'Değiştirmek için sunucu ayar dosyasında OPENREPORTING_PLUGINS değerini düzenleyip servisleri yeniden başlatın. Eklentiler uygulamanın yetkileriyle çalışır; yalnız güvendiğiniz eklentileri ekleyin.' })),
    h('div', { class: 'card' }, data.plugins.length
      ? h('table', { class: 'list' }, h('tr', ['Kimlik', 'Ad', 'Tür', 'Sürüm', 'Durum', 'Ayrıntı'].map((t) => h('th', { text: t }))),
        data.plugins.map((p) => {
          const [cls, label] = STATE[p.state] || ['', p.state];
          const browserNote = p.kind === 'panel' && p.state === 'loaded' && !inBrowser.has(p.id) ? 'Tarayıcıda yüklenemedi (konsolu kontrol edin)' : '';
          return h('tr', h('td', { class: 'mono', text: p.id }), h('td', { text: p.name }), h('td', { text: KIND[p.kind] || p.kind }),
            h('td', { text: p.version || '—' }), h('td', h('span', { class: `badge ${cls}`, text: label })), h('td', { class: 'muted', text: p.error || browserNote }));
        }))
      : h('p', { class: 'muted', text: 'Kurulu eklenti bulunamadı.' })));
}
