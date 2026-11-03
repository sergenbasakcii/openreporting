"""Synthetic Oracle CI acceptance through real nginx HTTPS; never a production target."""

import json
import os
from pathlib import Path
import secrets
import ssl
import time

import httpx
import pyotp

from openreporting import db, security
from openreporting.config import Settings
from openreporting.worker import run_forever


def main():
    if os.getenv("OPENREPORTING_ORACLE_CI") != "1" or not Path("/.dockerenv").exists():
        raise SystemExit("Disposable Oracle CI container required")
    settings = Settings.from_env()
    password = secrets.token_urlsafe(32)
    db.init_db(settings)
    security.create_user(settings, "oracle_fixture", password, "admin")
    context = ssl.create_default_context(cafile="/etc/pki/tls/certs/openreporting.crt")
    with httpx.Client(base_url="https://localhost", verify=context, trust_env=False, timeout=30) as client:
        for _ in range(30):
            try:
                if client.get("/api/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("Disposable HTTPS fixture did not start")
        response = client.post("/api/login", json={"username": "oracle_fixture", "password": password})
        assert response.status_code == 200
        headers = {"X-CSRF-Token": response.json()["csrf"]}
        assert client.get("/api/user").status_code == 403
        setup = client.post("/api/user/mfa/setup", json={"password": password}, headers=headers)
        assert setup.status_code == 200
        seed = setup.json()
        confirmed = client.post(
            "/api/user/mfa/confirm", json={"password": password, "setup_token": seed["setup_token"], "code": pyotp.TOTP(seed["secret"]).now()}, headers=headers
        )
        assert confirmed.status_code == 200
        assert client.get("/api/session").status_code == 401
        response = client.post("/api/login", json={"username": "oracle_fixture", "password": password, "otp": confirmed.json()["recovery_codes"][0]})
        assert response.status_code == 200
        headers = {"X-CSRF-Token": response.json()["csrf"]}
        assert client.get("/readyz").status_code == 200
        dash = {
            "uid": "oracle-fixture",
            "title": "Oracle OS fixture",
            "panels": [
                {"id": 1, "type": "timeseries", "title": "Synthetic", "targets": [{"refId": "A", "datasource": {"uid": "testdata"}, "scenario": "sine"}]}
            ],
        }
        assert client.post("/api/dashboards/db", json={"dashboard": dash}, headers=headers).status_code == 200
        report = client.post(
            "/api/dash-reports", json={"name": "Oracle OS report", "dashboard_uid": "oracle-fixture", "formats": ["pdf", "xlsx", "csv"]}, headers=headers
        )
        assert report.status_code == 201
        rid = report.json()["id"]
        run = client.post(f"/api/dash-reports/{rid}/runs", json={}, headers=headers)
        assert run.status_code == 200
        run_forever(settings, once=True)
        runs = client.get(f"/api/dash-reports/{rid}/runs").json()
        assert runs[0]["status"] == "completed"
        for kind, magic in [("pdf", b"%PDF"), ("xlsx", b"PK"), ("csv", None)]:
            downloaded = client.get(f"/api/report-runs/{run.json()['run_id']}/files/{kind}")
            assert downloaded.status_code == 200 and downloaded.content
            if magic:
                assert downloaded.content.startswith(magic)
        assert client.get("/metrics").status_code == 404
        assert client.post("/api/logout", headers=headers).status_code == 200
    print(
        json.dumps(
            {
                "https": True,
                "required_mfa": True,
                "recovery_login": True,
                "report_formats": ["pdf", "xlsx", "csv"],
                "worker": True,
                "public_metrics_blocked": True,
                "live_accounts_used": False,
            }
        )
    )


if __name__ == "__main__":
    main()
