// Admin → Teams: user groups that folder and dashboard permissions are granted to.
import { h, button, input, field, toast, modal, confirmDialog, loading, clear } from '../dom.js';
import { icon } from '../icons.js';
import { get, post, put, del } from '../api.js';
import { setBreadcrumbs } from '../router.js';

function teamDialog(team, done) {
  const m = { name: team?.name || '', description: team?.description || '' };
  const dlg = modal({ title: team ? 'Takımı düzenle' : 'Yeni takım', body: h('div',
    field('Takım adı', input({ value: m.name, placeholder: 'ör. NOC ekibi', onInput: (e) => { m.name = e.target.value; } })),
    field('Açıklama', input({ value: m.description, placeholder: 'ör. 7/24 ağ izleme', onInput: (e) => { m.description = e.target.value; } }))),
  footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Kaydet', { variant: 'primary', onClick: async () => {
    try {
      if (team) await put(`/api/teams/${team.id}`, m); else await post('/api/teams', m);
      dlg.close(); toast('Takım kaydedildi', 'ok'); done();
    } catch (err) { toast(err.message, 'error'); }
  } })] });
}

function membersDialog(team, users, done) {
  const selected = new Set(team.members.map((u) => u.id));
  let filter = '';
  const list = h('div', { class: 'grant-list' });
  const draw = () => {
    clear(list);
    for (const u of users.filter((x) => !filter || `${x.username} ${x.display_name || ''}`.toLowerCase().includes(filter))) {
      const box = h('input', { type: 'checkbox', checked: selected.has(u.id), 'aria-label': u.username, onChange: (e) => { if (e.target.checked) selected.add(u.id); else selected.delete(u.id); } });
      list.append(h('label', { class: 'grant-row' }, box, h('span', { class: 'grant-name' }, h('b', { text: u.display_name || u.username }),
        h('span', { class: 'hint', text: `${u.username} · ${{ admin: 'Yönetici', editor: 'Editör', viewer: 'İzleyici' }[u.role] || u.role}${u.active ? '' : ' · devre dışı'}` }))));
    }
  };
  draw();
  const dlg = modal({ title: `Üyeler · ${team.name}`, body: h('div',
    h('p', { class: 'muted', text: 'Takıma verilen klasör ve dashboard izinleri tüm üyelere uygulanır. Uygulama rolü (izleyici/editör) yine de üst sınırdır.' }),
    input({ placeholder: 'Kullanıcı ara', label: 'Kullanıcı ara', onInput: (e) => { filter = e.target.value.toLowerCase(); draw(); } }), list),
  footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Kaydet', { variant: 'primary', onClick: async () => {
    try { const r = await put(`/api/teams/${team.id}/members`, { user_ids: [...selected] }); dlg.close(); toast(`${r.added} eklendi, ${r.removed} çıkarıldı`, 'ok'); done(); } catch (err) { toast(err.message, 'error'); }
  } })] });
}

export async function teamsPage(root) {
  setBreadcrumbs([{ label: 'Yönetim' }, { label: 'Takımlar' }]);
  const page = h('div', { class: 'page' });
  root.append(page);
  const draw = async () => {
    clear(page).append(loading());
    const [teams, users] = await Promise.all([get('/api/teams'), get('/api/users')]);
    const people = users.filter((u) => !u.service_account);
    clear(page).append(h('div', { class: 'page-header' }, h('div', h('h1', icon('users'), 'Takımlar'),
      h('p', { class: 'sub', text: 'Kullanıcıları gruplayın; klasör ve dashboard izinlerini kişi kişi değil takım olarak verin.' })),
    h('div', { class: 'toolbar' }, button('Yeni takım', { icon: 'plus', variant: 'primary', onClick: () => teamDialog(null, draw) }))));
    if (!teams.length) {
      page.append(h('div', { class: 'empty-state' }, h('h2', { class: 'section-heading', text: 'Henüz takım yok' }),
        h('p', { text: 'Örneğin “NOC ekibi”, “Finans”, “Yönetim” takımları oluşturup üyeleri ekleyin; ardından klasör veya dashboard menüsündeki İzinler bölümünden takıma erişim verin.' })));
      return;
    }
    page.append(h('div', { class: 'card-grid' }, teams.map((t) => h('div', { class: 'card team-card' },
      h('div', { class: 'toolbar', style: { justifyContent: 'space-between' } }, h('h2', { class: 'section-heading', style: { margin: 0 }, text: t.name }),
        h('span', { class: 'badge info', text: `${t.members.length} üye` })),
      t.description ? h('p', { class: 'muted', text: t.description }) : null,
      h('div', { class: 'avatar-row' }, t.members.slice(0, 12).map((u) => h('span', { class: 'avatar sm', title: u.username, text: (u.display_name || u.username).slice(0, 2).toUpperCase() })),
        t.members.length > 12 ? h('span', { class: 'hint', text: `+${t.members.length - 12}` }) : null),
      h('div', { class: 'toolbar' },
        button('Üyeler', { size: 'sm', icon: 'users', onClick: () => membersDialog(t, people, draw) }),
        button('Düzenle', { size: 'sm', icon: 'edit', onClick: () => teamDialog(t, draw) }),
        button('Sil', { size: 'sm', icon: 'trash', variant: 'danger', onClick: async () => {
          if (!(await confirmDialog('Takımı sil', `${t.name} silinir; bu takıma verilmiş tüm izinler kalkar.`, { danger: true, okText: 'Sil' }))) return;
          try { await del(`/api/teams/${t.id}`); toast('Takım silindi', 'ok'); draw(); } catch (err) { toast(err.message, 'error'); }
        } }))))));
  };
  await draw();
}
