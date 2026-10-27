// Minimal, safe Markdown → DOM (no HTML passthrough). Links: http(s), relative and mailto only.
import { h } from './dom.js';

// "/path" is allowed but "//host" (protocol-relative) and "/\host" are not: browsers treat both as off-site.
function safeHref(url) {
  const value = String(url || '').trim();
  if (/^(https?:\/\/|#|mailto:)/i.test(value)) return value;
  if (/^\/(?![/\\])/.test(value)) return value;
  return null;
}

function inline(text) {
  const nodes = [];
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0;
  let m;
  while ((m = pattern.exec(text))) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const token = m[0];
    if (m[1]) nodes.push(h('code', { text: token.slice(1, -1) }));
    else if (m[2]) nodes.push(h('strong', inline(token.slice(2, -2))));
    else if (m[3]) nodes.push(h('em', inline(token.slice(1, -1))));
    else {
      const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
      const href = safeHref(lm[2]);
      nodes.push(href ? h('a', { href, target: href.startsWith('http') ? '_blank' : undefined, rel: 'noopener noreferrer' }, inline(lm[1])) : lm[1]);
    }
    last = m.index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function renderMarkdown(source, interpolateFn = (s) => s) {
  const root = h('div', { class: 'markdown' });
  const lines = interpolateFn(String(source || '')).replace(/\r/g, '').split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const body = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) { body.push(lines[i]); i += 1; }
      root.append(h('pre', h('code', { text: body.join('\n') })));
      i += 1;
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) { root.append(h(`h${heading[1].length}`, inline(heading[2]))); i += 1; continue; }
    if (/^\s*[-*]\s+/.test(line)) {
      const ul = h('ul');
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { ul.append(h('li', inline(lines[i].replace(/^\s*[-*]\s+/, '')))); i += 1; }
      root.append(ul);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const ol = h('ol');
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { ol.append(h('li', inline(lines[i].replace(/^\s*\d+\.\s+/, '')))); i += 1; }
      root.append(ol);
      continue;
    }
    if (/^\|.*\|$/.test(line.trim())) {
      const table = h('table');
      while (i < lines.length && /^\|.*\|$/.test(lines[i].trim())) {
        const cells = lines[i].trim().slice(1, -1).split('|').map((c) => c.trim());
        if (!cells.every((c) => /^:?-+:?$/.test(c))) table.append(h('tr', cells.map((c) => h('td', inline(c)))));
        i += 1;
      }
      root.append(table);
      continue;
    }
    if (/^---+$/.test(line.trim())) { root.append(h('hr')); i += 1; continue; }
    if (!line.trim()) { i += 1; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*[-*]\s|\s*\d+\.\s|\|)/.test(lines[i])) { para.push(lines[i]); i += 1; }
    root.append(h('p', inline(para.join(' '))));
  }
  return root;
}
