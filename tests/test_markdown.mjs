// Text panels: author markup renders, interpolated variable values never become links or markup.
import test from 'node:test';
import assert from 'node:assert/strict';

class Node {}
class Element extends Node {
  constructor(tag) { super(); this.tag = tag; this.children = []; this.attrs = {}; this.style = {}; this.dataset = {}; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener() {}
  set textContent(value) { this.children = [String(value)]; }
}
globalThis.Node = Node;
globalThis.document = { createElement: (tag) => new Element(tag), createTextNode: (text) => text };
const { renderMarkdown, escapeMarkdown } = await import('../openreporting/static/app/markdown.js');

const flat = (n) => (typeof n === 'string' ? n : `${n.tag === 'a' ? `<a ${n.attrs.href}>` : ''}${n.children.map(flat).join('')}`);
const links = (n) => (typeof n === 'string' ? [] : [...(n.tag === 'a' ? [n.attrs.href] : []), ...n.children.flatMap(links)]);

test('interpolated values with link markup stay plain text', () => {
  const evil = '[Re-login](https://evil.example) **x** `y`';
  const root = renderMarkdown('Host: $host', (s) => s.replace('$host', escapeMarkdown(evil)));
  assert.deepEqual(links(root), []);
  assert.equal(flat(root), `Host: ${evil}`);
});

test('author links and emphasis still render', () => {
  const root = renderMarkdown('[Detay](/d/x) **kalın** and [ext](https://example.com)');
  assert.deepEqual(links(root), ['/d/x', 'https://example.com']);
});

test('unsafe schemes are never links', () => {
  assert.deepEqual(links(renderMarkdown('[a](javascript:alert(1)) [b](//evil.example)')), []);
});
