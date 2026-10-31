"""Dashboard report engine: group sections, PDF/XLSX/CSV, schedules, archive integrity, API."""
import io
import json
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from openreporting import dashboards
from openreporting.config import Settings
from openreporting.db import connect
from openreporting.reporting import service
from openreporting.security import create_user
from openreporting.web import create_app

DS = {"uid": "testdata"}


def target(ref, item, functions=None, **extra):
    return {"refId": ref, "datasource": DS, "scenario": "zabbix_sim", "group": {"filter": "$group"},
            "host": {"filter": "$host"}, "item": {"filter": item}, "functions": functions or [], **extra}


DASHBOARD = {
    "uid": "rep-test", "title": "Rapor testi", "time": {"from": "now-6h", "to": "now"},
    "templating": {"list": [
        {"name": "group", "type": "custom", "query": "Linux servers,WAN Routers", "current": {"value": "WAN Routers"}},
        {"name": "host", "type": "query", "datasource": DS, "query": {"type": "host", "group": "$group"},
         "multi": True, "includeAll": True, "current": {"value": ["$__all"]}}]},
    "panels": [
        {"id": 1, "type": "row", "title": "Özet", "gridPos": {"x": 0, "y": 0, "w": 24, "h": 1}},
        {"id": 2, "type": "timeseries", "title": "CPU $host", "gridPos": {"x": 0, "y": 1, "w": 12, "h": 8},
         "targets": [target("A", "CPU utilization")], "fieldConfig": {"defaults": {"unit": "percent"}, "overrides": []},
         "options": {"legend": {"displayMode": "table", "calcs": ["mean", "max"]}}},
        {"id": 3, "type": "stat", "title": "Bellek", "gridPos": {"x": 12, "y": 1, "w": 6, "h": 4},
         "targets": [target("A", "Memory utilization")], "options": {"colorMode": "background"}},
        {"id": 4, "type": "gauge", "title": "Kayıp", "gridPos": {"x": 18, "y": 1, "w": 6, "h": 4},
         "targets": [target("A", "ICMP loss")]},
        {"id": 5, "type": "table", "title": "Özet tablo", "gridPos": {"x": 12, "y": 5, "w": 12, "h": 6},
         "targets": [target("A", "/CPU|Memory/")], "transformations": [{"id": "reduceByLabel", "options": {"label": "host"}}]},
        {"id": 6, "type": "piechart", "title": "Pay", "gridPos": {"x": 0, "y": 9, "w": 6, "h": 6}, "targets": [target("A", "CPU utilization")]},
        {"id": 7, "type": "bargauge", "title": "Top", "gridPos": {"x": 6, "y": 9, "w": 6, "h": 6}, "targets": [target("A", "CPU utilization")]},
        {"id": 8, "type": "statusgrid", "title": "Izgara", "gridPos": {"x": 12, "y": 11, "w": 6, "h": 4}, "targets": [target("A", "CPU utilization")]},
        {"id": 9, "type": "statetimeline", "title": "Durum", "gridPos": {"x": 18, "y": 11, "w": 6, "h": 4}, "targets": [target("A", "ICMP loss")]},
        {"id": 10, "type": "barchart", "title": "Çubuk", "gridPos": {"x": 0, "y": 15, "w": 12, "h": 6}, "targets": [target("A", "CPU utilization")]},
        {"id": 11, "type": "text", "title": "Not", "gridPos": {"x": 12, "y": 15, "w": 12, "h": 3},
         "options": {"content": "# Başlık $group\n- madde **kalın**"}},
    ]}


@pytest.fixture
def env(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path, secure_cookie=False, zabbix_url="", zabbix_token_file="", mail_enabled=False, recipient_domains=("example.org",))
    app = create_app(settings)
    admin_id = create_user(settings, "admin1", "an-admin-password-123", "admin")
    create_user(settings, "viewer1", "a-viewer-password-123", "viewer")
    user = {"id": admin_id, "role": "admin", "username": "admin1"}
    dashboards.save(settings, user, json.loads(json.dumps(DASHBOARD)))
    return settings, app, user


def test_group_report_sections_and_all_formats(env):
    settings, _, user = env
    created = service.save_report(settings, user, {"name": "WAN haftalık", "dashboard_uid": "rep-test",
                                                   "time_range": {"from": "now-6h", "to": "now"}, "split_by": "host",
                                                   "formats": ["pdf", "xlsx", "csv"], "timezone": "Europe/Istanbul"})
    queued = service.request_run(settings, user, created["id"], {})
    run_id = service.claim(settings)
    assert run_id == queued["run_id"]
    service.execute(settings, run_id)
    run = service.list_runs(settings, created["id"])[0]
    assert run["status"] == "completed", run
    assert set(run["files"]) == {"pdf", "xlsx", "csv", "manifest"}
    pdf = (settings.archive_dir / run["files"]["pdf"]).read_bytes()
    assert pdf.startswith(b"%PDF") and len(pdf) > 10_000
    with zipfile.ZipFile(io.BytesIO((settings.archive_dir / run["files"]["xlsx"]).read_bytes())) as book:
        sheets = [n for n in book.namelist() if n.startswith("xl/worksheets/")]
    assert len(sheets) > 5
    csv_text = (settings.archive_dir / run["files"]["csv"]).read_bytes().decode("utf-8-sig")
    assert "wan-rtr-ist" in csv_text and "CPU utilization" in csv_text
    manifest = json.loads((settings.archive_dir / run["files"]["manifest"]).read_text(encoding="utf8"))
    assert len(manifest["sections"]) == 5 and manifest["sections"][0].startswith("host: wan-rtr")
    path, _ = service.verified_file(settings, run_id, "pdf")
    assert path.is_file()
    (settings.archive_dir / run["files"]["pdf"]).write_bytes(pdf[:-10])
    with pytest.raises(service.ReportError, match="uyuşmuyor"):
        service.verified_file(settings, run_id, "pdf")


def test_missing_datasource_makes_report_partial_and_blocks_mail(env):
    settings, _, user = env
    broken = json.loads(json.dumps(DASHBOARD))
    broken["uid"] = "broken"
    broken["title"] = "Bozuk"
    broken["panels"][1]["targets"][0]["datasource"] = {"uid": "does-not-exist"}
    dashboards.save(settings, user, broken)
    settings_mail = replace(settings, mail_enabled=True, smtp_host="smtp.example.org", smtp_from="r@example.org")
    created = service.save_report(settings, user, {"name": "Kısmi", "dashboard_uid": "broken", "formats": ["pdf"]})
    with connect(settings) as db:
        row = db.execute("SELECT * FROM dash_reports WHERE id=?", (created["id"],)).fetchone()
        from openreporting.db import transaction
        with transaction(db):
            run_id = service.enqueue(db, row, user["id"], "2026-10-01T00:00:00+00:00", "2026-10-01T06:00:00+00:00",
                                     None, ["ops@example.org"])
    service.claim(settings_mail)
    service.execute(settings_mail, run_id)
    run = service.list_runs(settings, created["id"])[0]
    assert run["status"] == "partial"
    assert run["delivery_status"] == "blocked_partial"
    assert any("bulunamadı" in w for w in run["warnings"])


def test_schedule_math_and_periods():
    ref = datetime(2026, 10, 24, 10, 30, tzinfo=timezone.utc)  # Saturday, 13:30 Istanbul
    assert service.next_due("daily", "Europe/Istanbul", 8, 0, reference=ref) == "2026-10-25T05:00:00+00:00"
    assert service.next_due("weekly", "Europe/Istanbul", 8, 0, weekday=0, reference=ref) == "2026-10-26T05:00:00+00:00"
    assert service.next_due("monthly", "Europe/Istanbul", 7, 30, month_day=1, reference=ref) == "2026-11-01T04:30:00+00:00"
    assert service.next_due("hourly", "Europe/Istanbul", 0, 5, reference=ref) == "2026-10-24T11:05:00+00:00"


def test_scheduled_enqueue_is_idempotent_and_does_not_duplicate_audit(env):
    from openreporting.db import transaction, verify_audit
    settings, _, user = env
    created = service.save_report(settings, user, {"name": "Queue test", "dashboard_uid": "rep-test", "formats": ["csv"]})
    with connect(settings) as db, transaction(db):
        report = db.execute("SELECT * FROM dash_reports WHERE id=?", (created["id"],)).fetchone()
        args = (db, report, user["id"], "2026-10-01T00:00:00+00:00", "2026-10-02T00:00:00+00:00")
        first = service.enqueue(*args, schedule_id="schedule-test")
        assert service.enqueue(*args, schedule_id="schedule-test") == first
        assert db.execute("SELECT COUNT(*) FROM dash_report_runs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM audit WHERE action='report_run.queued'").fetchone()[0] == 1
        # Manual requests intentionally represent separate jobs for the same period.
        assert service.enqueue(*args) != service.enqueue(*args)
        assert verify_audit(db) == (True, None)


def test_dashboard_star_is_idempotent_and_scoped_to_user(env):
    settings, _, user = env
    dashboards.star(settings, user, "rep-test")
    dashboards.star(settings, user, "rep-test")
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM dashboard_stars WHERE user_id=?", (user["id"],)).fetchone()[0] == 1
        viewer = dict(db.execute("SELECT id,role FROM users WHERE username='viewer1'").fetchone())
    assert len(dashboards.search(settings, user, starred=True)) == 1
    assert dashboards.search(settings, viewer, starred=True) == []
    dashboards.star(settings, user, "rep-test", False)
    dashboards.star(settings, user, "rep-test", False)
    assert dashboards.search(settings, user, starred=True) == []
    start, end = service.schedule_period("daily", "Europe/Istanbul", "2026-10-25T05:00:00+00:00", "previous_period", {})
    assert start == "2026-10-23T21:00:00+00:00" and end == "2026-10-24T21:00:00+00:00"
    start, end = service.schedule_period("weekly", "Europe/Istanbul", "2026-10-26T05:00:00+00:00", "previous_period", {})
    assert start.startswith("2026-10-18T21:00") and end.startswith("2026-10-25T21:00")


def test_schedule_rules_and_tick(env):
    settings, _, user = env
    created = service.save_report(settings, user, {"name": "Günlük", "dashboard_uid": "rep-test"})
    editor = {"id": user["id"], "role": "editor"}
    with pytest.raises(service.ReportError, match="yönetici"):
        service.save_schedule(settings, editor, created["id"], {"cadence": "daily", "enabled": True})
    with pytest.raises(service.ReportError, match="E-posta kapalı"):
        service.save_schedule(settings, user, created["id"], {"cadence": "daily", "enabled": True, "recipients": ["a@example.org"]})
    sched = service.save_schedule(settings, user, created["id"], {"cadence": "hourly", "minute": 0, "enabled": True})
    with connect(settings) as db:
        db.execute("UPDATE dash_report_schedules SET next_due=? WHERE id=?",
                   (datetime.now(timezone.utc).replace(microsecond=0).isoformat(), sched["id"]))
    service.tick_schedules(settings)
    runs = service.list_runs(settings, created["id"])
    assert len(runs) == 1 and runs[0]["schedule_id"] == sched["id"]
    service.tick_schedules(settings)
    assert len(service.list_runs(settings, created["id"])) == 1


def test_report_api_permissions_preview_and_export(env):
    settings, app, _ = env
    with TestClient(app, base_url="http://localhost") as http:
        csrf = http.post("/api/login", json={"username": "viewer1", "password": "a-viewer-password-123"}).json()["csrf"]
        h = {"X-CSRF-Token": csrf}
        assert http.post("/api/dash-reports", json={"name": "x1", "dashboard_uid": "rep-test"}, headers=h).status_code == 403
        export = http.post("/api/dashboards/export", json={"dashboard_uid": "rep-test", "format": "pdf"}, headers=h)
        assert export.status_code == 200 and export.content.startswith(b"%PDF")
        http.post("/api/logout", headers=h)
        csrf = http.post("/api/login", json={"username": "admin1", "password": "an-admin-password-123"}).json()["csrf"]
        h = {"X-CSRF-Token": csrf}
        body = {"name": "API raporu", "dashboard_uid": "rep-test", "split_by": "host", "layout": "simple", "formats": ["pdf", "xlsx"]}
        preview = http.post("/api/dash-reports/preview", json={**body, "max_sections": 2}, headers=h)
        assert preview.status_code == 200 and preview.content.startswith(b"%PDF")
        xlsx = http.post("/api/dash-reports/preview", json={**body, "format": "xlsx"}, headers=h)
        assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
        rid = http.post("/api/dash-reports", json=body, headers=h).json()["id"]
        run = http.post(f"/api/dash-reports/{rid}/runs", json={}, headers=h).json()
        service.execute(settings, service.claim(settings))
        download = http.get(f"/api/report-runs/{run['run_id']}/files/pdf")
        assert download.status_code == 200 and download.content.startswith(b"%PDF")
        assert http.get(f"/api/report-runs/{run['run_id']}/files/../../etc").status_code == 404
        bad = http.post("/api/dash-reports", json={**body, "dashboard_uid": "nope"}, headers=h)
        assert bad.status_code == 404
        assert http.delete(f"/api/dash-reports/{rid}", headers=h).status_code == 200


def _png(color=(30, 90, 200, 255), size=(240, 80)):
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGBA", size, color).save(out, format="PNG")
    return out.getvalue()


def test_customer_logo_upload_and_pdf_embedding(env):
    import base64
    from fastapi.testclient import TestClient
    from openreporting.reporting import logos
    settings, app, user = env
    with TestClient(app, base_url="http://localhost") as http:
        csrf = http.post("/api/login", json={"username": "viewer1", "password": "a-viewer-password-123"}).json()["csrf"]
        data = "data:image/png;base64," + base64.b64encode(_png()).decode()
        assert http.post("/api/dash-reports/logos", headers={"X-CSRF-Token": csrf}, json={"data": data}).status_code == 403
        csrf = http.post("/api/login", json={"username": "admin1", "password": "an-admin-password-123"}).json()["csrf"]
        bad = http.post("/api/dash-reports/logos", headers={"X-CSRF-Token": csrf},
                        json={"data": base64.b64encode(b"<svg onload=alert(1)></svg>").decode()})
        assert bad.status_code == 422
        res = http.post("/api/dash-reports/logos", headers={"X-CSRF-Token": csrf}, json={"data": data})
        assert res.status_code == 201, res.text
        logo = res.json()
        assert (logo["width"], logo["height"]) == (240, 80)
        img = http.get(f"/api/dash-reports/logos/{logo['id']}")
        assert img.status_code == 200 and img.content.startswith(b"\x89PNG")
        assert http.get("/api/dash-reports/logos/../../state").status_code == 404
    # Unknown logo ids are refused in a report definition.
    with pytest.raises(logos.LogoError):
        service.save_report(settings, user, {"name": "Logo", "dashboard_uid": "rep-test", "logo_id": "0" * 64})
    created = service.save_report(settings, user, {"name": "Logolu rapor", "dashboard_uid": "rep-test", "logo_id": logo["id"],
                                                   "time_range": {"from": "now-6h", "to": "now"}, "formats": ["pdf"]})
    config = service.get_report(settings, created["id"])["config"]
    assert config["logo_id"] == logo["id"] and config["logo_on_cover"] and config["logo_on_pages"]
    start, end = datetime.now(timezone.utc) - timedelta(hours=6), datetime.now(timezone.utc)
    _, with_logo, _ = service.build_outputs(settings, config, "Logolu rapor", start, end)
    _, without, _ = service.build_outputs(settings, {**config, "logo_id": None}, "Logosuz rapor", start, end)
    assert b"/Subtype /Image" in with_logo["pdf"] and b"/Subtype /Image" not in without["pdf"]
    assert b"/Creator (OpenReporting)" in with_logo["pdf"]


def test_logo_normalisation_rejects_bad_input():
    from openreporting.reporting import logos
    with pytest.raises(logos.LogoError):
        logos.normalize(b"not an image")
    with pytest.raises(logos.LogoError):
        logos.normalize(_png(color=(0, 0, 0, 0)))  # fully transparent
    big = logos.normalize(_png(size=(3000, 600)))
    from io import BytesIO
    from PIL import Image
    assert max(Image.open(BytesIO(big)).size) <= logos.MAX_EDGE


def test_restart_marks_completed_but_sending_delivery_unknown_and_never_requeues(env):
    settings, _, user = env
    created = service.save_report(settings, user, {"name": "Interrupted mail", "dashboard_uid": "rep-test", "formats": ["csv"]})
    run_id = service.request_run(settings, user, created["id"], {})["run_id"]
    with connect(settings) as db:
        db.execute("UPDATE dash_report_runs SET status='completed',delivery_status='sending' WHERE id=?", (run_id,))
    service.mark_interrupted(settings, force=True)
    run = service.list_runs(settings, created["id"])[0]
    assert (run["status"], run["delivery_status"]) == ("completed", "unknown")
    assert service.claim(settings) is None
