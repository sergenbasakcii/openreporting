# Browser acceptance checks

`theme-surfaces.cjs` checks a running local preview without saving users, data sources,
dashboards or profile preferences. It logs in and uses the read-only PDF preview endpoint.

Provide `UI_TEST_USER` and `UI_TEST_PASSWORD` through the process environment. Playwright
must be available to Node; optionally point `OPENREPORTING_PLAYWRIGHT_MODULE` at an existing
installation. No browser dependency is added to the application runtime.

Run `node tests/browser/theme-surfaces.cjs`.

Optional settings: `OPENREPORTING_UI_URL` (default `http://127.0.0.1:8811`),
`OPENREPORTING_UI_DASHBOARD` (default `preview`), `OPENREPORTING_UI_OUTPUT` (default
`build/theme-audit`). Use an existing sample dashboard and an administrator test account.

The check covers dark/light native option surfaces, time/refresh/panel menus, panel
view and inspector, data source/report/profile/editor selects, all 20 new chart
tooltip colors and canvas replacement, system-theme changes, and the PDF loading
window. It confirms theme changes do not re-query data. Screenshots remain outside Git.
