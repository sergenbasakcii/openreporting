"""Turn a dashboard + report config into data-filled sections (one per split value)."""

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime

from .. import dashboard_runtime, query_engine
from ..domain import DomainError
from ..templating import ALL, interpolate

log = logging.getLogger(__name__)
NO_QUERY_TYPES = {"text", "row", "image", "divider", "reportinfo"}


@dataclass
class PanelResult:
    panel: dict
    title: str
    frames: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    interval_ms: int = 0
    warnings: list = field(default_factory=list)
    period: tuple | None = None  # (from_ms, to_ms) when the panel has its own time range


@dataclass
class Section:
    title: str
    variables: dict
    panels: list  # PanelResult (rows included as type "row" with no frames)


@dataclass
class Collected:
    dashboard: dict
    variables: dict
    sections: list
    start: datetime
    end: datetime
    timezone: str
    warnings: list = field(default_factory=list)

    @property
    def partial(self):
        return bool(self.warnings) or any(p.errors or p.warnings for s in self.sections for p in s.panels)


def _absolute_range(start, end):
    return {"from": str(int(start.timestamp() * 1000)), "to": str(int(end.timestamp() * 1000))}


def _variable_text(variable):
    value = variable.get("value")
    values = value if isinstance(value, list) else [value]
    if ALL in values:
        return "Tümü"
    return ", ".join(str(next((o["text"] for o in variable.get("options", []) if o["value"] == v), v)) for v in values)


def variable_summary(variables):
    return [(v.get("label") or name, _variable_text(v)) for name, v in variables.items() if v.get("type") != "constant"]


def collect(settings, dashboard, config, start, end, *, user="report", max_sections=500, panel_filter=None, section_limit=None, trusted=True):
    """Resolve variables once, then query every (section × panel).

    ``section_limit`` stops after N sections (previews); ``trusted=False`` formats
    variable values strictly, for exports requested by viewers.
    """
    tz = config.get("timezone") or "UTC"
    rng = _absolute_range(start, end)
    request = {"range": rng, "timezone": tz}
    overrides = dict(config.get("variables") or {})
    variables, warnings = dashboard_runtime.resolve_variables(settings, dashboard, overrides, request, user=user, trusted=trusted)
    split = config.get("split_by")
    section_vars = []
    if split:
        if split not in variables:
            raise DomainError(f"Bölümleme değişkeni dashboard’da yok: ${split}")
        values = dashboard_runtime.expanded_values(variables[split])
        if not values:
            raise DomainError(f"${split} için değer bulunamadı; rapor üretilmedi")
        if len(values) > max_sections:
            raise DomainError(f"${split} {len(values)} değer döndürdü; rapor başına en fazla {max_sections} bölüm")
        for value in values[:section_limit] if section_limit else values:
            scoped = dashboard_runtime._scoped(variables, split, value)  # noqa: SLF001 - shared helper
            # Dependent variables (e.g. $item depending on $host) re-resolve for the section.
            dep_overrides = {**overrides, split: value}
            dependent, dep_warn = dashboard_runtime.resolve_variables(settings, dashboard, dep_overrides, request, user=user, trusted=trusted)
            warnings.extend(w for w in dep_warn if w not in warnings)
            dependent[split] = scoped[split]
            section_vars.append((f"{variables[split].get('label') or split}: {scoped[split].get('text', value)}", dependent))
    else:
        section_vars.append(("", variables))
    sections = []
    wanted = set(config.get("panel_ids") or []) or None
    for title, scope in section_vars:
        panels = dashboard_runtime.expand(dashboard, scope, include_collapsed=config.get("include_collapsed", True))
        results = []
        for panel in panels:
            if split and panel.get("type") == "row" and panel.get("repeat") == split:
                continue  # the section header already names the split value
            source_id = panel.get("repeatPanelId", panel.get("id"))
            if wanted and panel.get("type") != "row" and source_id not in wanted and panel.get("id") not in wanted:
                continue
            if panel_filter and not panel_filter(panel):
                continue
            local = {**scope, **(panel.get("scopedVars") or {})}
            result = PanelResult(panel=panel, title=interpolate(panel.get("title", ""), local))
            if panel.get("timeRange"):
                own = _panel_range(panel, rng, tz)
                result.period = (int(own["from"]), int(own["to"]))
            if panel.get("type") not in NO_QUERY_TYPES and panel.get("targets"):
                try:
                    response = query_engine.run(
                        settings,
                        {
                            "targets": copy.deepcopy(panel["targets"]),
                            "datasource": panel.get("datasource"),
                            "range": _panel_range(panel, rng, tz),
                            "timezone": tz,
                            "maxDataPoints": max(10, min(int(panel.get("maxDataPoints") or 600), 20000)),
                            "minInterval": panel.get("interval"),
                            "variables": local,
                            "transformations": panel.get("transformations") or [],
                            "dashboardTitle": dashboard.get("title", ""),
                            "compare": (panel.get("options") or {}).get("compare"),
                        },
                        user=user,
                        trusted=trusted,
                    )
                    result.frames = response["frames"]
                    result.interval_ms = int(response["request"]["intervalMs"])
                    for ref, res in response["results"].items():
                        if res.get("error"):
                            result.errors.append(f"{ref}: {res['error']}")
                        result.warnings.extend(f"{ref}: {w}" for w in res.get("warnings") or [])
                    if response.get("transformError"):
                        result.errors.append(f"Dönüşüm: {response['transformError']}")
                except (DomainError, ValueError) as exc:
                    result.errors.append(str(exc))
                except Exception as exc:  # noqa: BLE001 - one failing panel must not abort the report
                    log.exception("Report panel query failed")
                    result.errors.append(f"Sorgu başarısız: {type(exc).__name__}")
            if panel.get("type") == "reportinfo":
                # Per-host sections must show that section's selection, not the report-wide "all".
                result.panel = {**panel, "_variables": variable_summary(scope)}
            if panel.get("type") == "text":
                content = (panel.get("options") or {}).get("content", "")
                result.panel = {**panel, "options": {**(panel.get("options") or {}), "content": interpolate(content, local)}}
            results.append(result)
        sections.append(Section(title=title, variables=scope, panels=results))
    return Collected(dashboard=dashboard, variables=variables, sections=sections, start=start, end=end, timezone=tz, warnings=warnings)


def _panel_range(panel, rng, tz="UTC"):
    own = panel.get("timeRange")
    if own:
        # Relative periods ("now-1y") are anchored at the report end, so a scheduled report for a past
        # period shows the year up to that period, not up to the moment it was rendered.
        from datetime import datetime, timezone

        from ..timerange import resolve_range

        anchor = datetime.fromtimestamp(int(rng["to"]) / 1000, timezone.utc)
        start, end = resolve_range(own["from"], own["to"], tz, now=anchor)
        rng = {"from": str(int(start.timestamp() * 1000)), "to": str(int(end.timestamp() * 1000))}
        if not panel.get("timeShift"):
            return rng
    if panel.get("timeFrom") or panel.get("timeShift"):
        frm, to = rng["from"], rng["to"]
        if panel.get("timeFrom"):
            from ..timerange import parse_duration

            to_ms = int(to)
            frm = str(to_ms - int(parse_duration(panel["timeFrom"]) * 1000))
        if panel.get("timeShift"):
            from ..timerange import parse_duration

            shift = int(parse_duration(panel["timeShift"]) * 1000)
            frm, to = str(int(frm) - shift), str(int(to) - shift)
        return {"from": frm, "to": to}
    return rng
