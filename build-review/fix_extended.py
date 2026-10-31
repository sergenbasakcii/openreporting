"""Review fixes for panels/extended.js: time zone, integer bins, units, heatmap fallback."""
from pathlib import Path

p = Path("openreporting/static/app/panels/extended.js")
t = p.read_text(encoding="utf-8")


def rep(old, new):
    global t
    if old not in t:
        raise SystemExit(f"not found: {old[:70]!r}")
    t = t.replace(old, new, 1)


rep("import { chartTheme, initChart, noData, reducedValues, reduce, minOf, maxOf } from './common.js';",
    "import { chartTheme, initChart, noData, reducedValues, reduce, minOf, maxOf, timeAxisLabel } from './common.js';\n"
    "import { formatValue, resolveUnit } from '../units.js';\n"
    "import { render as renderTimeSeries } from './timeseries.js';")
rep("const finite = v => typeof v === 'number' && Number.isFinite(v);",
    "const finite = v => typeof v === 'number' && Number.isFinite(v);\n"
    "// Dates follow the dashboard time zone like the other panels ('browser' = local).\n"
    "const zoneOf = tz => (!tz || tz === 'browser' ? undefined : tz === 'utc' ? 'UTC' : tz);\n"
    "function dayKey(ms, tz) {\n"
    " try { return new Intl.DateTimeFormat('en-CA', { timeZone: zoneOf(tz), year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms)); }\n"
    " catch { return new Date(ms).toISOString().slice(0, 10); }\n"
    "}\n"
    "function stamp(ms, tz) {\n"
    " try { return new Intl.DateTimeFormat('tr-TR', { timeZone: zoneOf(tz), dateStyle: 'short', timeStyle: 'short' }).format(new Date(ms)); }\n"
    " catch { return new Date(ms).toISOString(); }\n"
    "}")
rep("export function extendedOption(frames, panel) {", "export function extendedOption(frames, panel, tz) {")
# stacked area / step: time axis labels in the dashboard zone
rep("return {xAxis:{type:'time'},yAxis:{type:'value'},series:series.map(",
    "const span=Math.max(1,maxOf(series.flatMap(f=>f.points.map(p=>p[0])),0)-minOf(series.flatMap(f=>f.points.map(p=>p[0])),0));\n"
    "  return {xAxis:{type:'time',axisLabel:{hideOverlap:true,formatter:v=>timeAxisLabel(v,span,tz)}},yAxis:{type:'value'},series:series.map(")
# histogram: integer bin count
rep("const n=Math.max(1,Math.min(50,Number(panel.options?.bins)||10));",
    "const n=Math.max(1,Math.min(50,Math.floor(Number(panel.options?.bins))||10));")
# heatmap: labels in zone; non-series data keeps the previous (time series) rendering
rep("if(!series.length)return {message:'Isı haritası için zaman serisi seçin.'};",
    "if(!series.length)return {fallback:'timeseries'};")
rep("data:times.map(t=>new Date(t).toLocaleString())", "data:times.map(t=>stamp(t,tz))")
# calendar heatmap: bucket days in the dashboard zone
rep("const day=new Date(p[0]).toISOString().slice(0,10);", "const day=dayKey(p[0],tz);")
rep("export function renderExtended(container,frames,panel){\n const option=extendedOption(frames,panel);",
    "// Value formatting (unit/decimals) shared by tooltips and value axes.\n"
    "function valueFormat(frames,panel){\n"
    " const d=panel.fieldConfig?.defaults||{};const first=frames.find(f=>f.unit||f.columns?.some(c=>c.unit));\n"
    " const unit=resolveUnit(d.unit,first?.unit||first?.columns?.find(c=>c.unit)?.unit);\n"
    " return v=>(finite(v)?formatValue(v,unit,d.decimals):String(v??''));\n"
    "}\n"
    "export function renderExtended(container,frames,panel,ctx={}){\n"
    " const option=extendedOption(frames,panel,ctx.timezone);\n"
    " if(option?.fallback==='timeseries')return renderTimeSeries(container,frames,{...panel,type:'timeseries'},ctx);")
rep("textStyle:{color:theme.text}},...option},true);", "textStyle:{color:theme.text},valueFormatter:fmt},...option},true);")
rep(" const theme=chartTheme();\n",
    " const theme=chartTheme();\n"
    " const fmt=valueFormat(frames,panel);\n"
    " if(option.yAxis&&!Array.isArray(option.yAxis)&&option.yAxis.type==='value')"
    "option.yAxis={...option.yAxis,axisLabel:{...option.yAxis.axisLabel,formatter:fmt}};\n")
p.write_bytes(t.encode("utf-8"))
print("extended.js patched")
