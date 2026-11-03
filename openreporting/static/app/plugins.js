// Panel / query-editor plugins: allow-listed ES modules served same-origin from /plugins/<id>/.
// A plugin module exports `register(api)`. The api only offers registration and the safe DOM helper
// (no innerHTML path); plugins still run with the user's privileges, so operators allow-list them.
import { h, clear } from './dom.js';
import { PLUGINS } from './panels/registry.js';

const PLUGIN_ID = /^x-[a-z0-9][a-z0-9-]{1,39}$/;
export const QUERY_EDITORS = {};
export const LOADED = [];

function registerPanel(id, definition) {
  if (!PLUGIN_ID.test(id)) throw new Error(`Eklenti panel kimliği x- ile başlamalı: ${id}`);
  if (PLUGINS[id]) throw new Error(`Panel türü zaten kayıtlı: ${id}`);
  if (!definition || typeof definition.render !== 'function' || typeof definition.name !== 'string') {
    throw new Error(`${id}: name (metin) ve render(container, frames, panel, ctx) gerekli`);
  }
  PLUGINS[id] = { icon: 'panel', defaults: {}, sections: [], ...definition, plugin: true };
}

function registerQueryEditor(datasourceType, editor) {
  if (!PLUGIN_ID.test(datasourceType) || typeof editor !== 'function') throw new Error('Sorgu düzenleyici: x- türü ve fonksiyon gerekli');
  QUERY_EDITORS[datasourceType] = editor;
}

export async function loadPlugins(list) {
  const api = Object.freeze({ registerPanel, registerQueryEditor, dom: Object.freeze({ h, clear }) });
  for (const plugin of list || []) {
    try {
      if (plugin.style_url) document.head.append(h('link', { rel: 'stylesheet', href: plugin.style_url }));
      const module = await import(plugin.module_url);
      const register = module.register || module.default;
      if (typeof register !== 'function') throw new Error('register(api) dışa aktarılmamış');
      await register(api);
      LOADED.push({ id: plugin.id, name: plugin.name, version: plugin.version });
    } catch (err) {
      // One broken plugin must not break the application.
      console.warn(`Eklenti yüklenemedi: ${plugin.id}`, err); // eslint-disable-line no-console
    }
  }
}
