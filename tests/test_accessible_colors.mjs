import test from 'node:test';
import assert from 'node:assert/strict';
import { readableColor } from '../openreporting/static/app/colors.js';

function ratio(fg, bg) {
  const channels = c => c.startsWith('#') ? [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16)) : c.match(/[\d.]+/g).map(Number);
  const light = c => channels(c).map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
    .reduce((a, v, i) => a + v * [.2126, .7152, .0722][i], 0);
  return (Math.max(light(fg), light(bg)) + .05) / (Math.min(light(fg), light(bg)) + .05);
}

test('threshold text stays readable on both panel themes without mutating palette inputs', () => {
  for (const bg of ['#ffffff', '#181b1f']) {
    for (const fg of ['#73BF69', '#FADE2A', '#F2495C', '#5794F2', '#B877D9']) {
      assert.ok(ratio(readableColor(fg, bg), bg) >= 4.5, `${fg} on ${bg}`);
    }
  }
});

test('existing sufficient contrast and unsupported colour syntax remain unchanged', () => {
  assert.equal(readableColor('#24292e', '#ffffff'), '#24292e');
  assert.equal(readableColor('var(--text)', '#ffffff'), 'var(--text)');
});
