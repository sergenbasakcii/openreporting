// Home: getting started, starred & recent dashboards, quick links.
import { h, button, tagEl, timeAgo, loading, toast } from '../dom.js';
import { icon } from '../icons.js';
import { get, post, datasourcesList, invalidate } from '../api.js';
import { navigate, setBreadcrumbs } from '../router.js';
import { sampleDashboards } from './samples.js';

export async function homePage(root, { app }) {
  setBreadcrumbs([{ label: 'Ana sayfa' }]);
  const page = h('div', { class: 'page' });
  root.append(page);
  page.append(loading());
  const [dashboards, sources] = await Promise.all([get('/api/search'), datasourcesList().catch(() => [])]);
  page.replaceChildren();
  const canEdit = ['admin', 'editor'].includes(app.user.role);
  page.append(h('div', { class: 'page-header' }, h('div', h('h1', { text: `Hoş geldiniz, ${app.user.display_name || app.user.username}` }),
    h('p', { class: 'sub', text: 'Zabbix, veri gölü, SQL, log ve metrik kaynaklarından dashboard ve rapor hazırlayın. Her yerden aramak için Ctrl+K.' }))));
  const hasReal = sources.some((s) => s.type !== 'testdata');
  const steps = h('div', { class: 'card-grid' },
    tile('database', hasReal ? 'Veri kaynakları bağlı' : '1. Zabbix’i bağlayın', hasReal ? `${sources.length} veri kaynağı tanımlı` : 'Zabbix API URL ve salt-okunur token ile veri kaynağı ekleyin.', app.user.role === 'admin' ? '/datasources' : null),
    tile('report', '2. Akıllı dashboard ile hızlı rapor', 'Şablon seçin, sayfaya sürükleyin, host ve anahtar kelimeyi seçin; logolu PDF hazır.', canEdit ? '/smart' : '/smart'),
    tile('apps', 'Dashboard oluşturun', 'Grup / host / item sorguları, değişkenler, 30’dan fazla görselleştirme.', canEdit ? '/dashboards/new' : '/dashboards'),
    tile('calendar', '3. Raporları zamanlayın', 'PDF / Excel / CSV; host başına bölümler, önceki dönemle karşılaştırma, e-posta teslimi.', '/reports'),
    canEdit ? tile('compass', 'Keşfet', 'Bir dashboard oluşturmadan metrikleri hızlıca sorgulayın.', '/explore') : null);
  page.append(steps);
  if (canEdit && !dashboards.length) {
    page.append(h('div', { class: 'card', style: { marginTop: '16px' } }, h('h2', { class: 'section-heading', text: 'Örnek dashboard’larla başlayın' }),
      h('p', { class: 'muted', text: 'Örnekler "TestData (sentetik)" veri kaynağının Zabbix simülasyonunu kullanır (gerçek veri değildir). Veri kaynağını değiştirerek gerçek Zabbix’e uyarlayabilirsiniz.' }),
      h('div', { class: 'toolbar' }, button('Örnek dashboard’ları ekle', { icon: 'plus', variant: 'primary', onClick: async (e) => {
        e.currentTarget.disabled = true;
        try {
          for (const d of sampleDashboards()) await post('/api/dashboards/import', { dashboard: d, overwrite: true });
          invalidate('search');
          toast('Örnek dashboard’lar eklendi', 'ok');
          navigate('/dashboards');
        } catch (err) { toast(err.message, 'error'); e.currentTarget.disabled = false; }
      } }))));
  }
  const starred = dashboards.filter((d) => d.isStarred);
  const recent = [...dashboards].sort((a, b) => String(b.updated).localeCompare(String(a.updated))).slice(0, 8);
  page.append(h('div', { class: 'split-2', style: { marginTop: '18px' } },
    h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Yıldızlı dashboard’lar' }), list(starred, 'Henüz yıldızlı dashboard yok. Dashboard başlığının yanındaki yıldız ile ekleyin.')),
    h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Son güncellenenler' }), list(recent, 'Henüz dashboard yok.'))));
}

function tile(iconName, title, text, href) {
  return h(href ? 'a' : 'div', { class: 'tile', href: href || undefined, 'data-link': href ? '' : undefined },
    h('div', { class: 'tile-icon' }, icon(iconName)), h('div', h('b', { text: title }), h('span', { text })));
}

function list(items, emptyText) {
  if (!items.length) return h('p', { class: 'muted', text: emptyText });
  return h('div', items.map((d) => h('a', { class: 'list-row', href: (d.tags || []).includes('akıllı') ? `/smart/${d.uid}` : d.url, 'data-link': '' }, icon((d.tags || []).includes('akıllı') ? 'report' : 'apps'), h('div', { class: 'grow' }, h('b', { text: d.title }),
    h('div', { class: 'faint', text: `${d.folderTitle} · ${timeAgo(d.updated)}` })), h('div', d.tags.slice(0, 3).map(tagEl)))));
}
