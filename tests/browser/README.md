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

`accessibility-surfaces.cjs` uses the same preview and credentials. Install the free
`@axe-core/playwright` package in a separate QA directory and set `OPENREPORTING_AXE_MODULE`
to that package's absolute path when it is outside normal Node resolution. Run
`node tests/browser/accessibility-surfaces.cjs`. The report defaults to
`build/a11y-report.json` (`OPENREPORTING_A11Y_OUTPUT` overrides it).

It checks login and eight administrator routes in dark/light themes for automated
WCAG 2 A/AA, WCAG 2.1 A/AA and best-practice rules, and fails on critical/serious
findings or page errors. Moderate/minor findings remain in the report for review.
Automated checks do not certify WCAG compliance or replace keyboard/screen-reader,
responsive, data-dependent and institution-specific acceptance.

The accessibility script also verifies real dialog Tab/Shift+Tab wrapping and Escape focus
restoration, panel menu arrow navigation, and section Space/Enter toggling without saving data.
