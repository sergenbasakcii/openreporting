// Clickable date-range calendar (two months, Monday first, Turkish names). Days are wall-clock days in the
// given time zone; the result is absolute epoch-ms strings the server accepts in every time range.
import { h, button, input, toggle } from './dom.js';
import { icon } from './icons.js';

const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
const WEEKDAYS = ['Pt', 'Sa', 'Ça', 'Pe', 'Cu', 'Ct', 'Pz'];
const DAY_MS = 86400000;

/** Day key "YYYY-MM-DD" ↔ [y, m, d] (m is 1-12). Keys sort chronologically as strings. */
export const dayKey = (y, m, d) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
const parseKey = (key) => key.split('-').map(Number);
const addDays = (key, n) => { const [y, m, d] = parseKey(key); const t = new Date(Date.UTC(y, m - 1, d) + n * DAY_MS); return dayKey(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate()); };
const daysBetween = (a, b) => Math.round((Date.UTC(...parseKey(b).map((v, i) => (i === 1 ? v - 1 : v))) - Date.UTC(...parseKey(a).map((v, i) => (i === 1 ? v - 1 : v)))) / DAY_MS);

/** Wall-clock parts of an instant in `tz`. */
export function zonedParts(epochMs, tz) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit' }).formatToParts(new Date(epochMs)).map((x) => [x.type, x.value]));
  return { y: Number(p.year), m: Number(p.month), d: Number(p.day), hh: Number(p.hour) % 24, mm: Number(p.minute) };
}

/** Wall-clock time in `tz` → epoch ms (two passes settle instants next to a DST change). */
export function wallToEpoch(y, m, d, hh, mm, tz) {
  const wall = Date.UTC(y, m - 1, d, hh, mm);
  const offset = (t) => { const p = zonedParts(t, tz); return Date.UTC(p.y, p.m - 1, p.d, p.hh, p.mm) - Math.floor(t / 60000) * 60000; };
  const first = wall - offset(wall);
  return wall - offset(first);
}

export function formatDay(key) { const [y, m, d] = parseKey(key); return `${d} ${MONTHS[m - 1]} ${y}`; }

/**
 * calendarRange({ from, to, timezone, maxToday, onPick }) → element.
 * from/to: epoch-ms strings (or null). onPick({ from, to, label }) fires on "Uygula".
 */
export function calendarRange({ from, to, timezone = 'UTC', maxToday = true, daysOnly = false, onPick }) {
  const tz = timezone;
  const today = (() => { const p = zonedParts(Date.now(), tz); return dayKey(p.y, p.m, p.d); })();
  const initial = (v) => (v && /^\d{10,}$/.test(String(v)) ? zonedParts(Number(v), tz) : null);
  const f0 = initial(from);
  const t0 = initial(to);
  // A range ending at midnight ends on the previous day ("1-30 Kasım" is 1 Kasım 00:00 → 1 Aralık 00:00);
  // one ending at 23:59 ("now-1d/d" resolves to 23:59:59.999) ends on that day. Both are whole days.
  const endsAtMidnight = t0 && t0.hh === 0 && t0.mm === 0;
  const endsAtDayEnd = t0 && t0.hh === 23 && t0.mm === 59;
  const state = {
    start: f0 ? dayKey(f0.y, f0.m, f0.d) : null,
    end: t0 ? (endsAtMidnight ? addDays(dayKey(t0.y, t0.m, t0.d), -1) : dayKey(t0.y, t0.m, t0.d)) : null,
    hover: null,
    // daysOnly: opened from a relative range ("son 1 yıl" ends at the current minute) — keep its days, not its clock times.
    allDay: daysOnly || (!(f0 && (f0.hh || f0.mm)) && (!t0 || endsAtMidnight || endsAtDayEnd)),
    startTime: f0 && !daysOnly ? `${String(f0.hh).padStart(2, '0')}:${String(f0.mm).padStart(2, '0')}` : '00:00',
    endTime: t0 && !endsAtMidnight && !daysOnly ? `${String(t0.hh).padStart(2, '0')}:${String(t0.mm).padStart(2, '0')}` : '23:59',
    focus: null,
  };
  const anchor = parseKey(state.end || state.start || today);
  // Show the selection's last month on the right.
  state.view = { y: anchor[1] === 1 ? anchor[0] - 1 : anchor[0], m: anchor[1] === 1 ? 12 : anchor[1] - 1 };
  state.focus = state.start || today;

  const root = h('div', { class: 'cal' });
  const summary = h('div', { class: 'cal-summary', role: 'status' });
  const months = h('div', { class: 'cal-months' });
  const timeRow = h('div', { class: 'cal-times' });
  const applyBtn = button('Uygula', { variant: 'primary', onClick: () => apply() });

  const inRange = (key) => {
    const end = state.end || (state.start && state.hover && state.hover >= state.start ? state.hover : null);
    return state.start && end && key > state.start && key < end;
  };

  function pick(key) {
    if (maxToday && key > today) return;
    if (!state.start || state.end || key < state.start) { state.start = key; state.end = null; }
    else state.end = key;
    state.focus = key;
    draw();
    root.querySelector(`[data-day="${key}"]`)?.focus();
  }

  function monthGrid(y, m) {
    const first = new Date(Date.UTC(y, m - 1, 1));
    const lead = (first.getUTCDay() + 6) % 7; // Monday first
    const count = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const cells = [];
    for (let i = 0; i < lead; i++) cells.push(h('span', { class: 'cal-pad', 'aria-hidden': 'true' }));
    for (let d = 1; d <= count; d++) {
      const key = dayKey(y, m, d);
      const disabled = maxToday && key > today;
      const cls = ['cal-day', key === today ? 'today' : '', key === state.start ? 'start' : '', key === (state.end || '') ? 'end' : '',
        inRange(key) ? 'in' : '', disabled ? 'off' : ''].filter(Boolean).join(' ');
      cells.push(h('button', { type: 'button', class: cls, text: String(d), 'data-day': key, disabled,
        tabindex: key === state.focus ? '0' : '-1', 'aria-label': formatDay(key), 'aria-pressed': String(key === state.start || key === state.end),
        onClick: () => pick(key),
        onMouseenter: () => { if (state.start && !state.end) { state.hover = key; paint(); } } }));
    }
    return h('div', { class: 'cal-month' }, h('div', { class: 'cal-title', text: `${MONTHS[m - 1]} ${y}` }),
      h('div', { class: 'cal-grid cal-head' }, WEEKDAYS.map((w) => h('span', { text: w }))),
      h('div', { class: 'cal-grid', role: 'group', 'aria-label': `${MONTHS[m - 1]} ${y}` }, cells));
  }

  // Hover only repaints classes: rebuilding the buttons would drop the pointer target.
  function paint() {
    for (const el of root.querySelectorAll('.cal-day')) el.classList.toggle('in', inRange(el.dataset.day));
    updateSummary();
  }

  function updateSummary() {
    if (!state.start) { summary.textContent = 'Başlangıç gününe tıklayın'; applyBtn.disabled = true; return; }
    if (!state.end) { summary.textContent = `${formatDay(state.start)} → bitiş gününe tıklayın`; applyBtn.disabled = true; return; }
    const days = daysBetween(state.start, state.end) + 1;
    summary.textContent = `${formatDay(state.start)} – ${formatDay(state.end)} · ${days} gün`;
    applyBtn.disabled = false;
  }

  function shiftView(n) {
    const t = state.view.y * 12 + (state.view.m - 1) + n;
    state.view = { y: Math.floor(t / 12), m: (t % 12) + 1 };
    draw();
  }

  function draw() {
    const next = state.view.m === 12 ? { y: state.view.y + 1, m: 1 } : { y: state.view.y, m: state.view.m + 1 };
    months.replaceChildren(
      button('', { icon: 'chevron-left', title: 'Önceki ay', onClick: () => shiftView(-1) }),
      monthGrid(state.view.y, state.view.m), monthGrid(next.y, next.m),
      button('', { icon: 'chevron-right', title: 'Sonraki ay', onClick: () => shiftView(1) }));
    const startIn = input({ type: 'time', value: state.startTime, label: 'Başlangıç saati', onChange: (e) => { state.startTime = e.target.value || '00:00'; } });
    const endIn = input({ type: 'time', value: state.endTime, label: 'Bitiş saati', onChange: (e) => { state.endTime = e.target.value || '23:59'; } });
    timeRow.replaceChildren(toggle('Tüm gün', state.allDay, (v) => { state.allDay = v; draw(); }),
      ...(state.allDay ? [] : [h('label', { class: 'cal-time' }, 'Başlangıç', startIn), h('label', { class: 'cal-time' }, 'Bitiş', endIn)]),
      h('span', { class: 'hint', text: `Saat dilimi: ${tz}` }));
    updateSummary();
  }

  function apply() {
    if (!state.start || !state.end) return;
    const [sy, sm, sd] = parseKey(state.start);
    const [ey, em, ed] = parseKey(state.end);
    let fromMs;
    let toMs;
    if (state.allDay) {
      fromMs = wallToEpoch(sy, sm, sd, 0, 0, tz);
      const [ny, nm, nd] = parseKey(addDays(state.end, 1));
      toMs = wallToEpoch(ny, nm, nd, 0, 0, tz);
    } else {
      const [shh, smm] = state.startTime.split(':').map(Number);
      const [ehh, emm] = state.endTime.split(':').map(Number);
      fromMs = wallToEpoch(sy, sm, sd, shh, smm, tz);
      toMs = wallToEpoch(ey, em, ed, ehh, emm, tz) + (state.endTime === '23:59' ? 60000 : 0);
    }
    if (toMs <= fromMs) return;
    onPick({ from: String(fromMs), to: String(toMs), label: summary.textContent });
  }

  // Roving focus: arrows move by day/week, PageUp/PageDown by month, Enter/Space picks.
  root.addEventListener('keydown', (e) => {
    const el = e.target.closest?.('.cal-day');
    if (!el) return;
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    const month = { PageUp: -1, PageDown: 1 }[e.key];
    if (!step && !month) return;
    e.preventDefault();
    let key = step ? addDays(el.dataset.day, step) : (() => { const [y, m, d] = parseKey(el.dataset.day); const t = y * 12 + m - 1 + month; return dayKey(Math.floor(t / 12), (t % 12) + 1, Math.min(d, 28)); })();
    if (maxToday && key > today) key = today;
    state.focus = key;
    const [ky, km] = parseKey(key);
    const visible = [state.view.y * 12 + state.view.m - 1, state.view.y * 12 + state.view.m];
    const target = ky * 12 + km - 1;
    if (target < visible[0]) shiftView(-1); else if (target > visible[1]) shiftView(1); else draw();
    root.querySelector(`[data-day="${key}"]`)?.focus();
  });

  root.append(months, timeRow, h('div', { class: 'cal-foot' }, icon('calendar'), summary, applyBtn));
  draw();
  root.focusDay = () => root.querySelector('.cal-day[tabindex="0"]')?.focus();
  return root;
}
