// Shared permission editor for folders and dashboards: grant view/edit to teams and users.
import { h, button, select, toggle, modal, toast, clear, input } from './dom.js';
import { icon } from './icons.js';
import { get, put, invalidate } from './api.js';

const LEVELS = [{ value: '', label: 'İzin yok' }, { value: 'view', label: 'Görüntüleme' }, { value: 'edit', label: 'Düzenleme' }];

// principals: [{ key, kind: 'team'|'user', id, label, hint, viewerOnly }]
function grantList(principals, choices) {
  let filter = '';
  const rows = h('div', { class: 'grant-list' });
  const draw = () => {
    clear(rows);
    const shown = principals.filter((p) => !filter || p.label.toLowerCase().includes(filter));
    for (const p of shown) {
      rows.append(h('div', { class: 'grant-row' },
        h('span', { class: 'grant-icon' }, icon(p.kind === 'team' ? 'users' : 'user')),
        h('span', { class: 'grant-name' }, h('b', { text: p.label }), h('span', { class: 'hint', text: p.hint })),
        select(LEVELS.filter((l) => l.value !== 'edit' || !p.viewerOnly || choices.get(p.key) === 'edit'), choices.get(p.key) || '',
          (v) => { if (v) choices.set(p.key, v); else choices.delete(p.key); }, { label: p.aria, class: 'auto-width' })));
    }
    if (!shown.length) rows.append(h('p', { class: 'muted', text: 'Eşleşen takım veya kullanıcı yok.' }));
  };
  draw();
  return h('div', input({ placeholder: 'Takım veya kullanıcı ara', label: 'Takım veya kullanıcı ara', onInput: (e) => { filter = e.target.value.toLowerCase(); draw(); } }), rows);
}

async function principalsOf() {
  const [users, teams] = await Promise.all([get('/api/users'), get('/api/teams')]);
  return [
    ...teams.map((t) => ({ key: `team:${t.id}`, kind: 'team', id: t.id, label: t.name, aria: `${t.name} (takım)`, hint: `Takım · ${t.members.length} üye` })),
    ...users.filter((u) => u.active && u.role !== 'admin' && !u.service_account).map((u) => ({
      key: `user:${u.id}`, kind: 'user', id: u.id, label: u.display_name || u.username, aria: `${u.username} (${u.role})`,
      hint: `Kullanıcı · ${{ editor: 'Editör', viewer: 'İzleyici' }[u.role] || u.role}${u.role === 'viewer' ? ' (düzenleme rolü gerekir)' : ''}`, viewerOnly: u.role === 'viewer' })),
  ];
}

function dialog({ title, intro, restrictLabel, policy, choices, principals, save }) {
  // Grants of principals that can no longer receive access (disabled users) are dropped on save.
  const known = new Set(principals.map((p) => p.key));
  for (const key of [...choices.keys()]) if (!known.has(key)) choices.delete(key);
  let restricted = policy.restricted;
  const list = grantList(principals, choices);
  const show = () => { list.hidden = !restricted; };
  show();
  const dlg = modal({ title, body: h('div', h('p', { text: intro }), toggle(restrictLabel, restricted, (v) => { restricted = v; show(); }), list,
    h('p', { class: 'faint', text: 'Yöneticiler her zaman erişir. İzin değişikliği ilgili rapor zamanlamalarını kapatır; yeniden onay gerekir.' })),
  footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Kaydet', { variant: 'primary', onClick: async () => {
    try { await save(restricted); invalidate(''); dlg.close(); toast('İzinler kaydedildi', 'ok'); } catch (err) { toast(err.message, 'error'); }
  } })] });
}

export async function folderPermissionsDialog(folder, refresh) {
  try {
    const [policy, principals] = await Promise.all([get(`/api/folders/${folder.uid}/permissions`), principalsOf()]);
    const choices = new Map([...policy.grants.map((g) => [`user:${g.user_id}`, g.permission]), ...(policy.team_grants || []).map((g) => [`team:${g.team_id}`, g.permission])]);
    dialog({ title: `Klasör izinleri: ${folder.title}`, restrictLabel: 'Klasör erişimini kısıtla', policy, choices, principals,
      intro: 'Paylaşılan klasörü herkes görür. Kısıtlı klasöre yalnızca seçtiğiniz takımlar ve kullanıcılar erişir.',
      save: async (restricted) => {
        const grants = [...choices].filter(([k]) => k.startsWith('user:')).map(([k, permission]) => ({ user_id: k.slice(5), permission }));
        const team_grants = [...choices].filter(([k]) => k.startsWith('team:')).map(([k, permission]) => ({ team_id: k.slice(5), permission }));
        await put(`/api/folders/${folder.uid}/permissions`, { restricted, revision: policy.revision, grants, team_grants });
        refresh && refresh();
      } });
  } catch (err) { toast(err.message, 'error'); }
}

export async function dashboardPermissionsDialog(dash) {
  try {
    const [policy, principals] = await Promise.all([get(`/api/dashboards/uid/${encodeURIComponent(dash.uid)}/permissions`), principalsOf()]);
    const choices = new Map(policy.grants.map((g) => [`${g.principal_type}:${g.principal_id}`, g.permission]));
    dialog({ title: `Dashboard izinleri: ${dash.title}`, restrictLabel: 'Bu dashboard’u yalnız seçilenlere aç', policy, choices, principals,
      intro: 'Kapalıyken dashboard klasörünün izinlerini izler. Açıkken yalnızca seçtiğiniz takımlar ve kullanıcılar görür veya düzenler (klasör kısıtlı olsa bile).',
      save: async (restricted) => {
        const grants = [...choices].map(([k, permission]) => { const [principal_type, ...rest] = k.split(':'); return { principal_type, principal_id: rest.join(':'), permission }; });
        await put(`/api/dashboards/uid/${encodeURIComponent(dash.uid)}/permissions`, { restricted, revision: policy.revision, grants });
      } });
  } catch (err) { toast(err.message, 'error'); }
}
