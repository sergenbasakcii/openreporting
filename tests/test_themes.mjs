// Theme contract: every curated theme in themes.js has a token block in themes.css, the server list matches,
// and the important text/background pairs meet WCAG AA contrast (4.5:1) after alpha compositing.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { THEMES, resolveTheme, normalisePreference, oppositeTheme } from '../openreporting/static/app/themes.js';

const css = readFileSync(new URL('../openreporting/static/app/themes.css', import.meta.url), 'utf8');
const serverIds = readFileSync(new URL('../openreporting/themes.py', import.meta.url), 'utf8').match(/THEME_IDS = \(([^)]*)\)/)[1]
  .match(/"([a-z-]+)"/g).map((s) => s.slice(1, -1));

function tokens(id) {
  const start = css.search(new RegExp(`\\[data-theme="${id}"\\]\\s*\\{`));
  assert.ok(start >= 0, `themes.css has no block for ${id}`);
  const body = css.slice(css.indexOf('{', start) + 1, css.indexOf('\n}', start));
  return Object.fromEntries([...body.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

function rgba(value) {
  if (value.startsWith('#')) return [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16)).concat(1);
  const parts = value.match(/[\d.]+/g).map(Number);
  return parts.length === 3 ? parts.concat(1) : parts;
}
function over(fg, bg) {
  const [r, g, b, a] = rgba(fg); const base = rgba(bg);
  return [r, g, b].map((c, i) => c * a + base[i] * (1 - a)).concat(1);
}
function luminance([r, g, b]) {
  return [r, g, b].map((v) => v / 255).map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
    .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
}
function contrast(fg, bg) {
  const solidBg = over(bg, '#000000');
  const a = luminance(over(fg, `rgb(${solidBg.slice(0, 3).join(',')})`)); const b = luminance(solidBg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

test('client, stylesheet and server agree on the curated theme ids', () => {
  assert.deepEqual(THEMES.map((t) => t.id), serverIds);
  for (const theme of THEMES) assert.ok(['dark', 'light'].includes(theme.scheme), theme.id);
});

test('every theme defines the full token set', () => {
  const required = Object.keys(tokens('aurora'));
  for (const theme of THEMES) {
    const t = tokens(theme.id);
    for (const name of required) assert.ok(t[name], `${theme.id} is missing --${name}`);
    const series = t.series.split(',').map((c) => c.trim());
    assert.equal(series.length, 10, `${theme.id} series`);
    for (const c of series) assert.match(c, /^#[0-9a-f]{6}$/i);
  }
});

test('text, links and primary buttons meet WCAG AA in every theme', () => {
  for (const theme of THEMES) {
    const t = tokens(theme.id);
    for (const surface of ['bg', 'bg-panel', 'bg-elevated']) {
      for (const fg of ['text', 'text-strong', 'text-muted', 'text-faint', 'primary-text', 'success-text', 'error-text']) {
        const ratio = contrast(t[fg], t[surface]);
        assert.ok(ratio >= 4.5, `${theme.id}: --${fg} on --${surface} is ${ratio.toFixed(2)}:1`);
      }
    }
    const button = contrast(t['on-primary'], t.primary);
    assert.ok(button >= 4.5, `${theme.id}: --on-primary on --primary is ${button.toFixed(2)}:1`);
  }
});

test('preferences resolve legacy values, unknown ids and the opposite-scheme toggle', () => {
  assert.equal(resolveTheme('dark').id, 'aurora');
  assert.equal(resolveTheme('light').id, 'porcelain');
  assert.equal(resolveTheme('no-such-theme').id, 'aurora');
  assert.equal(normalisePreference('light'), 'porcelain');
  assert.equal(normalisePreference('system'), 'system');
  assert.equal(normalisePreference('<script>'), 'aurora');
  for (const theme of THEMES) {
    const other = THEMES.find((t) => t.id === oppositeTheme(theme.id));
    assert.notEqual(other.scheme, theme.scheme, theme.id);
  }
});
