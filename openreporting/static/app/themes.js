// Curated themes. Tokens live in themes.css; this list drives the pickers and the system mapping.
// Keep the ids in sync with openreporting/themes.py (the server validates saved preferences).
import { setPalette } from './colors.js';

export const THEMES = Object.freeze([
  { id: 'aurora', name: 'Aurora', scheme: 'dark', description: 'Lacivert yüzeyler, camgöbeği vurgu. Varsayılan koyu tema.', swatch: ['#0b1020', '#121a2e', '#2dd4bf', '#818cf8'] },
  { id: 'porcelain', name: 'Porselen', scheme: 'light', description: 'Sıcak beyaz, mürekkep metin, koyu camgöbeği. Varsayılan açık tema.', swatch: ['#f4f3ef', '#ffffff', '#0d9488', '#4f46e5'] },
  { id: 'graphite', name: 'Grafit', scheme: 'dark', description: 'Nötr kömür grisi, kehribar vurgu. İzleme odaları ve duvar ekranları için.', swatch: ['#121315', '#1a1c1f', '#f59e0b', '#38bdf8'] },
  { id: 'dune', name: 'Kum', scheme: 'light', description: 'Kâğıt tonları, kiremit vurgu. Uzun rapor okumaları için.', swatch: ['#f6f0e6', '#fffbf5', '#c2410c', '#0f766e'] },
  { id: 'contrast', name: 'Yüksek kontrast', scheme: 'dark', description: 'Siyah zemin, beyaz metin, sarı odak. Erişilebilirlik ve parlak ortamlar için.', swatch: ['#000000', '#0a0a0a', '#ffd60a', '#00e5ff'] },
]);
export const SYSTEM = 'system';
export const DEFAULT_THEME = 'aurora';
const LEGACY = Object.freeze({ dark: 'aurora', light: 'porcelain' });
const SYSTEM_PAIR = Object.freeze({ dark: 'aurora', light: 'porcelain' });
const BY_ID = Object.freeze(Object.fromEntries(THEMES.map((t) => [t.id, t])));

/** Preference value ('system', a theme id or a legacy dark/light) → a concrete theme. */
export function resolveTheme(preference) {
  const pref = LEGACY[preference] || preference;
  if (pref === SYSTEM) {
    const light = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
    return BY_ID[SYSTEM_PAIR[light ? 'light' : 'dark']];
  }
  return BY_ID[pref] || BY_ID[DEFAULT_THEME];
}

/** Normalise a stored preference so pickers show the right option for legacy values. */
export function normalisePreference(preference) {
  const pref = LEGACY[preference] || preference;
  return pref === SYSTEM || BY_ID[pref] ? pref : DEFAULT_THEME;
}

/** The theme with the opposite scheme, for the quick toggle in the user menu. */
export function oppositeTheme(themeId) {
  const theme = BY_ID[themeId] || BY_ID[DEFAULT_THEME];
  return theme.scheme === 'dark' ? (themeId === 'graphite' || themeId === 'contrast' ? 'dune' : 'porcelain') : (themeId === 'dune' ? 'graphite' : 'aurora');
}

/** Read the active theme's series colours from CSS so charts follow the theme. */
export function syncSeriesPalette(root = document.documentElement) {
  const raw = getComputedStyle(root).getPropertyValue('--series');
  const colours = raw.split(',').map((c) => c.trim()).filter(Boolean);
  setPalette(colours);
}

export function applyThemeToDocument(themeId, root = document.documentElement) {
  const theme = BY_ID[themeId] || BY_ID[DEFAULT_THEME];
  // Swap all tokens at once: hover/colour transitions would otherwise animate through mixed themes.
  root.classList.add('theme-switching');
  root.dataset.theme = theme.id;
  root.dataset.scheme = theme.scheme;
  root.style.colorScheme = theme.scheme;
  syncSeriesPalette(root);
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('theme-switching')));
  return theme;
}

export function themeSwatch(theme, h) {
  return h('span', { class: 'theme-swatch', 'aria-hidden': 'true' },
    ...theme.swatch.map((c) => h('i', { style: { background: c } })));
}
