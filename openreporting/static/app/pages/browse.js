// Dashboard browser (folders, search, tags, starred) and the import page.
import { h, button, input, select, textarea, field, toggle, tagEl, timeAgo, clear, toast, confirmDialog, promptDialog, menu, loading } from '../dom.js';
import { icon } from '../icons.js';
import { get, post, put, del, invalidate } from '../api.js';
import { navigate, setBreadcrumbs } from '../router.js';
import { sampleDashboards } from './samples.js';

export async function browsePage(root, { app, query, folderUid }) {
  const params = new URLSearchParams(query || '');
  const canEdit = ['admin', 'editor'].includes(app.user.role);
  setBreadcrumbs([{ label: 'Dashboard’lar' }]);
  const state = { query: params.get('query') || '', tag: params.get('tag') || '', starred: params.get('starred') === '1', view: 'folders' };
  const page = h('div', { class: 'page' });
  const listHost = h('div');
  const searchIn = input({ value: state.query, placeholder: 'Dashboard ara…', onInput: (e) => { state.query = e.target.value; draw(); } });
  const tagSel = h('div');
  page.append(h('div', { class: 'page-header' }, h('div', h('h1', icon('apps'), 'Dashboard’lar'), h('p', { class: 'sub', text: 'Klasörler, etiketler ve yıldızlı dashboard’lar.' })),
    canEdit ? h('div', { class: 'toolbar' },
      button('Yeni klasör', { icon: 'folder', onClick: async () => {
        const title = await promptDialog('Yeni klasör', 'Klasör adı');
        if (!title) return;
        try { await post('/api/folders', { title }); toast('Klasör oluşturuldu', 'ok'); draw(); } catch (err) { toast(err.message, 'error'); }
      } }),
      button('İçe aktar', { icon: 'import', onClick: () => navigate('/dashboards/import') }),
      button('Yeni dashboard', { icon: 'plus', variant: 'primary', onClick: () => navigate('/dashboards/new') })) : null),
  h('div', { class: 'toolbar', style: { marginBottom: '14px' } }, h('div', { style: { flex: '1', minWidth: '240px' } }, searchIn), tagSel,
    toggle('Yalnızca yıldızlılar', state.starred, (v) => { state.starred = v; draw(); }),
    h('div', { class: 'segmented' }, h('button', { type: 'button', class: 'on', text: 'Klasör görünümü', onclick: (e) => { state.view = 'folders'; e.currentTarget.classList.add('on'); e.currentTarget.nextSibling.classList.remove('on'); draw(); } }),
      h('button', { type: 'button', text: 'Liste', onclick: (e) => { state.view = 'list'; e.currentTarget.classList.add('on'); e.currentTarget.previousSibling.classList.remove('on'); draw(); } }))), listHost);
  root.append(page);
  get('/api/dashboards/tags').then((tags) => {
    tagSel.append(select([{ value: '', label: 'Tüm etiketler' }, ...tags.map((t) => ({ value: t.term, label: `${t.term} (${t.count})` }))], state.tag, (v) => { state.tag = v; draw(); }));
  });
  let seq = 0;
  async function draw() {
    const mine = ++seq;
    const qs = new URLSearchParams();
    if (state.query) qs.set('query', state.query);
    if (state.tag) qs.set('tag', state.tag);
    if (state.starred) qs.set('starred', 'true');
    if (folderUid) qs.set('folderUid', folderUid);
    const [results, folders] = await Promise.all([get(`/api/search?${qs}`), get('/api/folders')]);
    if (mine !== seq) return;
    clear(listHost);
    if (!results.length && !folders.length) {
      listHost.append(h('div', { class: 'empty-state' }, h('h3', { text: 'Henüz dashboard yok' }),
        h('p', { text: 'Yeni bir dashboard oluşturun, Grafana JSON’u içe aktarın veya örnekleri ekleyin.' }),
        canEdit ? h('div', { class: 'toolbar' }, button('Yeni dashboard', { icon: 'plus', variant: 'primary', onClick: () => navigate('/dashboards/new') }),
          button('Örnekleri ekle', { icon: 'apps', onClick: async () => {
            for (const d of sampleDashboards()) await post('/api/dashboards/import', { dashboard: d, overwrite: true });
            invalidate('search'); draw();
          } })) : null));
      return;
    }
    const row = (d) => h('a', { class: 'list-row', href: d.url, 'data-link': '' }, icon('apps'), h('div', { class: 'grow' }, h('b', { text: d.title }),
      h('div', { class: 'faint', text: `${d.folderTitle} · güncellendi ${timeAgo(d.updated)}` })), h('div', d.tags.map(tagEl)), d.isStarred ? h('span', { class: 'star-on' }, icon('star')) : null);
    if (state.view === 'list' || state.query || state.tag || state.starred || folderUid) {
      if (!results.length) listHost.append(h('p', { class: 'muted', text: 'Eşleşen dashboard yok.' }));
      results.forEach((d) => listHost.append(row(d)));
      return;
    }
    const groups = new Map([['', { title: 'Genel', uid: '', items: [] }]]);
    for (const f of folders) groups.set(f.uid, { title: f.title, uid: f.uid, items: [] });
    for (const d of results) (groups.get(d.folderUid || '') || groups.get('')).items.push(d);
    for (const g of groups.values()) {
      const body = h('div', { style: { paddingLeft: '18px' } }, g.items.map(row), g.items.length ? null : h('p', { class: 'faint', text: 'Boş klasör' }));
      const head = h('div', { class: 'folder-head' }, icon('folder-open'), h('span', { text: g.title }), h('span', { class: 'faint', text: `(${g.items.length})` }), h('span', { class: 'spacer' }),
        canEdit && g.uid ? button('', { icon: 'dots', variant: 'ghost', size: 'sm', onClick: (e) => { e.stopPropagation(); menu(e.currentTarget, [
          { label: 'Yeniden adlandır', icon: 'edit', onClick: async () => { const t = await promptDialog('Klasörü yeniden adlandır', 'Ad', g.title); if (t) { try { await put(`/api/folders/${g.uid}`, { title: t }); draw(); } catch (err) { toast(err.message, 'error'); } } } },
          { label: 'Sil', icon: 'trash', onClick: async () => { if (await confirmDialog('Klasörü sil', 'Yalnızca boş klasörler silinebilir.', { danger: true, okText: 'Sil' })) { try { await del(`/api/folders/${g.uid}`); draw(); } catch (err) { toast(err.message, 'error'); } } } },
          { label: 'Bu klasörde yeni dashboard', icon: 'plus', onClick: () => navigate(`/dashboards/new?folderUid=${g.uid}`) }], { align: 'right' }); } }) : null);
      head.addEventListener('click', () => { body.hidden = !body.hidden; });
      listHost.append(head, body);
    }
  }
  await draw();
}

export async function importPage(root, { app }) {
  setBreadcrumbs([{ label: 'Dashboard’lar', href: '/dashboards' }, { label: 'İçe aktar' }]);
  const folders = await get('/api/folders').catch(() => []);
  const area = textarea({ rows: 18, class: 'code-editor', placeholder: '{ "title": "...", "panels": [...] }' });
  const folderSel = select([{ value: '', label: 'Genel' }, ...folders.map((f) => ({ value: f.uid, label: f.title }))], '', () => {});
  let overwrite = false;
  const file = h('input', { type: 'file', accept: '.json,application/json', onchange: async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    if (f.size > 3_000_000) { toast('Dosya 3 MB sınırını aşıyor', 'error'); return; }
    area.value = await f.text();
  } });
  const run = async () => {
    let dashboard;
    try { dashboard = JSON.parse(area.value); } catch (err) { toast(`Geçersiz JSON: ${err.message}`, 'error'); return; }
    if (dashboard.dashboard && dashboard.dashboard.panels) dashboard = dashboard.dashboard;
    try {
      const res = await post('/api/dashboards/import', { dashboard, folderUid: folderSel.value || null, overwrite });
      invalidate('search');
      toast('Dashboard içe aktarıldı', 'ok');
      navigate(res.url);
    } catch (err) { toast(err.message, 'error'); }
  };
  root.append(h('div', { class: 'page' }, h('div', { class: 'page-header' }, h('div', h('h1', icon('import'), 'Dashboard içe aktar'),
    h('p', { class: 'sub', text: 'Grafana dashboard JSON’u (Zabbix eklentisi sorguları dahil) veya OpenReporting dışa aktarımı yükleyin. Veri kaynakları türüne göre otomatik eşlenir.' }))),
  h('div', { class: 'card' }, field('JSON dosyası', file), field('veya JSON yapıştırın', area),
    h('div', { class: 'form-grid' }, field('Klasör', folderSel), field(null, toggle('Aynı uid varsa üzerine yaz', false, (v) => { overwrite = v; })))),
    h('div', { class: 'toolbar' }, button('İçe aktar', { icon: 'import', variant: 'primary', onClick: run }), button('Vazgeç', { onClick: () => navigate('/dashboards') })),
    h('div', { class: 'alert', style: { marginTop: '16px' } }, 'Desteklenmeyen Grafana eklenti panelleri bir uyarı metin paneline dönüştürülür; ',
      '“graph” ve “singlestat” gibi eski paneller modern zaman serisi ve stat panellerine çevrilir.')));
}

export { loading };
