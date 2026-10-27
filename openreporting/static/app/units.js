// Mirror of openreporting/units.py — keep identifiers in sync so screen and PDF agree.
const SI = ['', 'k', 'M', 'G', 'T', 'P', 'E'];
const IEC = ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei'];
export const ZABBIX_UNITS = { B: 'bytes', bps: 'bps', Bps: 'Bps', '%': 'percent', s: 's', uptime: 'dtdurations', unixtime: 'dateTimeAsIso',
  rpm: 'rpm', Hz: 'hertz', W: 'watt', V: 'volt', A: 'amp', C: 'celsius', '°C': 'celsius', dBm: 'dBm', ms: 'ms', pps: 'pps', iops: 'iops' };

const KNOWN = new Set(['none', 'short', 'percent', 'percentunit', 'humidity', 'dB', 'dBm', 'bytes', 'kbytes', 'mbytes', 'gbytes', 'decbytes',
  'bits', 'decbits', 'bps', 'binbps', 'Bps', 'binBps', 'pps', 'iops', 'ops', 'reqps', 'rpm', 'ns', 'µs', 'ms', 's', 'm', 'h', 'd',
  'dtdurations', 'dateTimeAsIso', 'hertz', 'celsius', 'fahrenheit', 'watt', 'kwatt', 'volt', 'amp']);

export function resolveUnit(unit, sourceUnit) {
  if (unit && unit !== 'auto') return unit;
  if (sourceUnit) {
    if (ZABBIX_UNITS[sourceUnit]) return ZABBIX_UNITS[sourceUnit];
    if (KNOWN.has(sourceUnit) || sourceUnit.startsWith('suffix:') || sourceUnit.startsWith('prefix:')) return sourceUnit;
    return `suffix: ${sourceUnit}`;
  }
  return 'short';
}

function decimalsFor(v, decimals) {
  if (decimals !== undefined && decimals !== null && decimals !== '') return Math.max(0, Math.min(10, Number(decimals)));
  const m = Math.abs(v);
  if (m === 0 || m >= 100) return 0;
  if (m >= 10) return 1;
  if (m >= 1) return 2;
  return 3;
}
function num(v, decimals) {
  let text = v.toFixed(decimalsFor(v, decimals));
  if ((decimals === undefined || decimals === null || decimals === '') && text.includes('.')) text = text.replace(/0+$/, '').replace(/\.$/, '');
  return text;
}
function scaled(v, base, prefixes, suffix, decimals) {
  let i = 0;
  while (Math.abs(v) >= base && i < prefixes.length - 1) { v /= base; i += 1; }
  return `${num(v, decimals)} ${prefixes[i]}${suffix}`.trim();
}
function short(v, decimals) {
  const suf = ['', ' K', ' Mn', ' Mr', ' Tn'];
  let i = 0;
  while (Math.abs(v) >= 1000 && i < suf.length - 1) { v /= 1000; i += 1; }
  return `${num(v, decimals)}${suf[i]}`;
}
function duration(s, decimals) {
  const sign = s < 0 ? '-' : '';
  s = Math.abs(s);
  if (s < 1e-6) return `${sign}${num(s * 1e9, decimals)} ns`;
  if (s < 1e-3) return `${sign}${num(s * 1e6, decimals)} µs`;
  if (s < 1) return `${sign}${num(s * 1e3, decimals)} ms`;
  if (s < 60) return `${sign}${num(s, decimals)} s`;
  if (s < 3600) return `${sign}${num(s / 60, decimals)} dk`;
  if (s < 86400) return `${sign}${num(s / 3600, decimals)} sa`;
  if (s < 604800 * 52) return `${sign}${num(s / 86400, decimals)} gün`;
  return `${sign}${num(s / 31536000, decimals)} yıl`;
}
function dtdurations(s) {
  s = Math.floor(Math.abs(s));
  const d = Math.floor(s / 86400); const h = Math.floor((s % 86400) / 3600); const m = Math.floor((s % 3600) / 60);
  const parts = [];
  if (d) parts.push(`${d} gün`);
  if (h) parts.push(`${h} sa`);
  if (m && !d) parts.push(`${m} dk`);
  if (!parts.length) parts.push(`${s % 60} sn`);
  return parts.slice(0, 2).join(' ');
}

export function formatValue(value, unit = 'short', decimals, noValue = 'Veri yok') {
  if (value === null || value === undefined || value === '') return noValue;
  const v = Number(value);
  if (!Number.isFinite(v)) return typeof value === 'string' ? value : noValue;
  unit = unit || 'short';
  if (unit.startsWith('suffix:')) return `${num(v, decimals)} ${unit.slice(7).trim()}`.trim();
  if (unit.startsWith('prefix:')) return `${unit.slice(7).trim()}${num(v, decimals)}`;
  switch (unit) {
    case 'none': return num(v, decimals);
    case 'short': return short(v, decimals);
    case 'percent': return `${num(v, decimals)}%`;
    case 'percentunit': return `${num(v * 100, decimals)}%`;
    case 'humidity': return `${num(v, decimals)}%H`;
    case 'dB': case 'dBm': return `${num(v, decimals)} ${unit}`;
    case 'bytes': return scaled(v, 1024, IEC, 'B', decimals);
    case 'kbytes': return scaled(v * 1024, 1024, IEC, 'B', decimals);
    case 'mbytes': return scaled(v * 1024 ** 2, 1024, IEC, 'B', decimals);
    case 'gbytes': return scaled(v * 1024 ** 3, 1024, IEC, 'B', decimals);
    case 'decbytes': return scaled(v, 1000, SI, 'B', decimals);
    case 'bits': return scaled(v, 1024, IEC, 'b', decimals);
    case 'decbits': return scaled(v, 1000, SI, 'b', decimals);
    case 'bps': return scaled(v, 1000, SI, 'bps', decimals);
    case 'binbps': return scaled(v, 1024, IEC, 'bps', decimals);
    case 'Bps': return scaled(v, 1000, SI, 'B/s', decimals);
    case 'binBps': return scaled(v, 1024, IEC, 'B/s', decimals);
    case 'pps': return `${short(v, decimals)} p/s`;
    case 'iops': return `${short(v, decimals)} io/s`;
    case 'ops': return `${short(v, decimals)} ops/s`;
    case 'reqps': return `${short(v, decimals)} req/s`;
    case 'rpm': return `${short(v, decimals)} rpm`;
    case 'ns': return duration(v / 1e9, decimals);
    case 'µs': return duration(v / 1e6, decimals);
    case 'ms': return duration(v / 1e3, decimals);
    case 's': return duration(v, decimals);
    case 'm': return duration(v * 60, decimals);
    case 'h': return duration(v * 3600, decimals);
    case 'd': return duration(v * 86400, decimals);
    case 'dtdurations': return dtdurations(v);
    case 'dateTimeAsIso': return new Date(v * 1000).toISOString().replace('T', ' ').slice(0, 19);
    case 'hertz': return scaled(v, 1000, SI, 'Hz', decimals);
    case 'celsius': return `${num(v, decimals)}°C`;
    case 'fahrenheit': return `${num(v, decimals)}°F`;
    case 'watt': return scaled(v, 1000, SI, 'W', decimals);
    case 'kwatt': return scaled(v * 1000, 1000, SI, 'W', decimals);
    case 'volt': return scaled(v, 1000, SI, 'V', decimals);
    case 'amp': return scaled(v, 1000, SI, 'A', decimals);
    default: return short(v, decimals);
  }
}

export const UNIT_GROUPS = [
  { group: 'Genel', units: [['none', 'Yok'], ['short', 'Kısa (K, Mn, Mr)'], ['percent', 'Yüzde (0-100)'], ['percentunit', 'Yüzde (0.0-1.0)'], ['humidity', 'Nem (%H)'], ['dB', 'Desibel'], ['dBm', 'dBm']] },
  { group: 'Veri', units: [['bytes', 'bayt (IEC)'], ['decbytes', 'bayt (SI)'], ['bits', 'bit (IEC)'], ['decbits', 'bit (SI)'], ['kbytes', 'kibibayt'], ['mbytes', 'mebibayt'], ['gbytes', 'gibibayt']] },
  { group: 'Veri hızı', units: [['bps', 'bit/sn (SI)'], ['binbps', 'bit/sn (IEC)'], ['Bps', 'bayt/sn (SI)'], ['binBps', 'bayt/sn (IEC)'], ['pps', 'paket/sn'], ['iops', 'G/Ç işlem/sn'], ['ops', 'işlem/sn'], ['reqps', 'istek/sn']] },
  { group: 'Zaman', units: [['ns', 'nanosaniye'], ['µs', 'mikrosaniye'], ['ms', 'milisaniye'], ['s', 'saniye'], ['m', 'dakika'], ['h', 'saat'], ['d', 'gün'], ['dtdurations', 'süre (gün/saat)'], ['dateTimeAsIso', 'Tarih/saat'], ['hertz', 'hertz']] },
  { group: 'Fiziksel', units: [['celsius', '°C'], ['fahrenheit', '°F'], ['watt', 'Watt'], ['kwatt', 'Kilowatt'], ['volt', 'Volt'], ['amp', 'Amper'], ['rpm', 'RPM']] },
];

export function unitOptions() {
  return [{ value: 'auto', label: 'Otomatik (Zabbix birimi)' }, ...UNIT_GROUPS.map((g) => ({ group: g.group, options: g.units.map(([value, label]) => ({ value, label: `${label} · ${value}` })) }))];
}
