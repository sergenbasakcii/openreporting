// Shared by the browser acceptance scripts: scan every curated theme (ids mirror openreporting/themes.py).
const THEMES = [
  { id: 'aurora', scheme: 'dark' },
  { id: 'porcelain', scheme: 'light' },
  { id: 'graphite', scheme: 'dark' },
  { id: 'dune', scheme: 'light' },
  { id: 'contrast', scheme: 'dark' },
];

async function applyTheme(page, theme) {
  await page.evaluate(({ id, scheme }) => {
    const root = document.documentElement;
    root.dataset.theme = id;
    root.dataset.scheme = scheme;
    root.style.colorScheme = scheme;
    window.dispatchEvent(new CustomEvent('openreporting:themechange', { detail: id }));
  }, theme);
  // Let hover/colour transitions (.15s) and chart redraws settle before measuring contrast.
  await page.waitForTimeout(250);
}

module.exports = { THEMES, THEME_IDS: THEMES.map(t => t.id), applyTheme };
