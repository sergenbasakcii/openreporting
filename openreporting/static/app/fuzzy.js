// Fuzzy ranking for the command palette (pure; unit-tested in tests/test_fuzzy.mjs).
// Subsequence match with bonuses for word starts and contiguous runs; -1 when the query does not match.
// Turkish-aware, accent-insensitive folding: "ozet" finds "Özet", "isik" finds "Işık".
const FOLD = { ç: 'c', ğ: 'g', ı: 'i', ö: 'o', ş: 's', ü: 'u', â: 'a', î: 'i', û: 'u' };
export const fold = (text) => String(text).toLocaleLowerCase('tr').replace(/[çğıöşüâîû]/g, (c) => FOLD[c]);

export function score(query, text) {
  const q = fold(query); const t = fold(text);
  if (!q) return 1;
  let pos = -1; let total = 0; let run = 0;
  for (const ch of q) {
    const next = t.indexOf(ch, pos + 1);
    if (next < 0) return -1;
    run = next === pos + 1 ? run + 1 : 0;
    total += 1 + run * 2 + (next === 0 || /[\s·/_-]/.test(t[next - 1]) ? 3 : 0);
    pos = next;
  }
  return total - t.length * 0.01;
}
