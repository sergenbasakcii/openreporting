// Paint a popup immediately, before async report generation or stylesheet loading.
export function preparePreviewWindow(win) {
  if (!win) return;
  const rootStyle = getComputedStyle(document.documentElement);
  const theme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  win.opener = null;
  const doc = win.document;
  doc.title = 'Önizleme hazırlanıyor…';
  doc.documentElement.lang = 'tr';
  doc.documentElement.dataset.theme = theme;
  doc.documentElement.style.colorScheme = theme;
  doc.documentElement.style.backgroundColor = rootStyle.getPropertyValue('--bg').trim();
  doc.body.style.backgroundColor = rootStyle.getPropertyValue('--bg').trim();
  doc.body.style.color = rootStyle.getPropertyValue('--text').trim();
  doc.body.style.margin = '0';
  doc.body.style.font = getComputedStyle(document.body).font;
  const css = doc.createElement('link');
  css.rel = 'stylesheet';
  css.href = new URL('/static/app/app.css', location.origin).href;
  doc.head.append(css);
  const loading = doc.createElement('main');
  loading.className = 'boot-splash';
  loading.style.cssText = 'min-height:100vh;display:grid;place-content:center;justify-items:center;gap:14px';
  loading.setAttribute('role', 'status');
  loading.setAttribute('aria-live', 'polite');
  const spinner = doc.createElement('span');
  spinner.className = 'spinner';
  spinner.style.cssText = 'width:16px;height:16px;border-radius:50%';
  spinner.style.border = `2px solid ${rootStyle.getPropertyValue('--border-strong').trim()}`;
  spinner.style.borderTopColor = rootStyle.getPropertyValue('--primary-text').trim();
  spinner.setAttribute('aria-hidden', 'true');
  const label = doc.createElement('p');
  label.textContent = 'Önizleme hazırlanıyor…';
  loading.append(spinner, label);
  doc.body.replaceChildren(loading);
}
