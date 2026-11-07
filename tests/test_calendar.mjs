// Date-range calendar maths: wall-clock days in a time zone → epoch ms, including DST changes.
import test from 'node:test';
import assert from 'node:assert/strict';
import { dayKey, formatDay, wallToEpoch, zonedParts } from '../openreporting/static/app/calendar.js';

test('Istanbul midnight is 21:00 UTC the day before', () => {
  assert.equal(new Date(wallToEpoch(2026, 11, 1, 0, 0, 'Europe/Istanbul')).toISOString(), '2026-10-31T21:00:00.000Z');
});

test('a whole month in Istanbul spans exactly its days', () => {
  const from = wallToEpoch(2026, 11, 1, 0, 0, 'Europe/Istanbul');
  const to = wallToEpoch(2026, 12, 1, 0, 0, 'Europe/Istanbul');
  assert.equal((to - from) / 3600000, 30 * 24);
});

test('Berlin day of the October DST change has 25 hours', () => {
  const from = wallToEpoch(2026, 10, 25, 0, 0, 'Europe/Berlin');
  const to = wallToEpoch(2026, 10, 26, 0, 0, 'Europe/Berlin');
  assert.equal((to - from) / 3600000, 25);
  assert.deepEqual(zonedParts(from, 'Europe/Berlin'), { y: 2026, m: 10, d: 25, hh: 0, mm: 0 });
});

test('Berlin day of the March DST change has 23 hours', () => {
  const from = wallToEpoch(2026, 3, 29, 0, 0, 'Europe/Berlin');
  const to = wallToEpoch(2026, 3, 30, 0, 0, 'Europe/Berlin');
  assert.equal((to - from) / 3600000, 23);
});

test('day keys sort chronologically and format in Turkish', () => {
  assert.ok(dayKey(2026, 2, 9) < dayKey(2026, 10, 1));
  assert.equal(formatDay('2026-11-06'), '6 Kasım 2026');
});
