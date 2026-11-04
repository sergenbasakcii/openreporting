import test from 'node:test';
import assert from 'node:assert/strict';
import { score } from '../openreporting/static/app/fuzzy.js';

test('palette ranking prefers word starts and contiguous matches', () => {
  assert.equal(score('xyz', 'Akıllı dashboard'), -1);
  assert.ok(score('akd', 'Akıllı dashboard') > 0);
  assert.ok(score('host', 'Host sağlık raporu') > score('host', 'Ağ ve erişilebilirlik · ghost-host'));
  assert.ok(score('noc ozet', 'Örnek · NOC özeti') > 0, 'accent-insensitive');
  assert.ok(score('ISIK', 'ışık raporu') > 0, 'Turkish dotless i');
  assert.equal(score('', 'anything'), 1);
});
