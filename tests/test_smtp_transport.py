"""Real local TLS sockets exercise SMTP negotiation and report delivery semantics."""

import base64
import os
import smtplib
import socketserver
import ssl
import threading
from contextlib import contextmanager
from dataclasses import replace
from email import policy
from email.parser import BytesParser

import pytest

from openreporting.config import Settings
from openreporting import mail_transport
from openreporting.reporting import service
from tests.tls_fixture import certificates


@contextmanager
def smtp_server(cert, key, *, implicit=False, starttls=True, auth=True, refused=(), drop_after_data=False):
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(cert, key)
    events, messages = [], []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            sock = self.request
            stream = None
            try:
                if implicit:
                    sock = tls.wrap_socket(sock, server_side=True)
                stream = sock.makefile("rb")

                def reply(value):
                    sock.sendall(value + b"\r\n")

                reply(b"220 localhost test")
                while True:
                    line = stream.readline(65536)
                    if not line:
                        break
                    command, _, args = line.decode().strip().partition(" ")
                    command = command.upper()
                    events.append((command, isinstance(sock, ssl.SSLSocket)))
                    if command == "EHLO":
                        reply(b"250-localhost")
                        if starttls and not isinstance(sock, ssl.SSLSocket):
                            reply(b"250-STARTTLS")
                        if auth and isinstance(sock, ssl.SSLSocket):
                            reply(b"250-AUTH PLAIN")
                        reply(b"250 SIZE 30000000")
                    elif command == "STARTTLS" and starttls:
                        reply(b"220 Ready for TLS")
                        stream.close()
                        sock = tls.wrap_socket(sock, server_side=True)
                        stream = sock.makefile("rb")
                    elif command == "AUTH":
                        assert isinstance(sock, ssl.SSLSocket), "Never authenticate on plaintext"
                        decoded = base64.b64decode(args.split(" ", 1)[1])
                        reply(b"235 authenticated" if decoded == b"\x00reporter\x00isolated-smtp-password" else b"535 rejected")
                    elif command == "RCPT" and any(addr.lower() in args.lower() for addr in refused):
                        reply(b"550 recipient rejected")
                    elif command == "DATA":
                        reply(b"354 End with dot")
                        lines = []
                        while True:
                            content = stream.readline(65536)
                            if content == b".\r\n":
                                break
                            if not content:
                                return
                            lines.append(content)
                        messages.append(b"".join(lines))
                        if drop_after_data:
                            return  # Acceptance response is lost: delivery is uncertain.
                        reply(b"250 queued")
                    elif command in {"MAIL", "RCPT", "NOOP", "RSET"}:
                        reply(b"250 ok")
                    elif command == "QUIT":
                        reply(b"221 bye")
                        break
                    else:
                        reply(b"502 unsupported")
            except (ssl.SSLError, ConnectionError, OSError):
                pass  # Expected for failed certificate/hostname checks.
            finally:
                if stream:
                    stream.close()
                sock.close()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_address[1], events, messages
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture
def setup(tmp_path):
    ca, cert, key = certificates(tmp_path)
    settings = replace(
        Settings.from_env(),
        data_dir=tmp_path,
        mail_enabled=True,
        smtp_host="localhost",
        smtp_from="reports@example.com",
        recipient_domains=("example.com",),
        smtp_timeout=3,
        smtp_user="reporter",
        smtp_password="isolated-smtp-password",
        smtp_ca_file=str(ca),
    )
    return settings, cert, key


@pytest.mark.parametrize(
    "mode",
    [
        "starttls",
        pytest.param(
            "tls",
            marks=pytest.mark.skipif(
                os.name == "nt", reason="Real implicit TLS trust is tested on Linux CI; local Windows endpoint security replaces fixture certificates"
            ),
        ),
    ],
)
def test_real_tls_auth_and_diagnostic_never_sends_mail(setup, mode):
    settings, cert, key = setup
    with smtp_server(cert, key, implicit=mode == "tls") as (port, events, messages):
        result = mail_transport.check_connection(replace(settings, smtp_port=port, smtp_security=mode))
        assert "gönderilmedi" in result
        assert ("AUTH", True) in events and ("NOOP", True) in events
        assert not any(cmd in {"MAIL", "RCPT", "DATA"} for cmd, _ in events)
        assert messages == []


def test_no_downgrade_no_untrusted_certificate_or_hostname(setup):
    settings, cert, key = setup
    with smtp_server(cert, key, starttls=False) as (port, events, _):
        with pytest.raises(smtplib.SMTPNotSupportedError):
            mail_transport.check_connection(replace(settings, smtp_port=port))
        assert not any(cmd in {"AUTH", "MAIL", "DATA"} for cmd, _ in events)
    for overrides in ({"smtp_ca_file": ""}, {"smtp_host": "127.0.0.1"}):
        with smtp_server(cert, key, implicit=True) as (port, events, _):
            with pytest.raises(ssl.SSLCertVerificationError):
                mail_transport.check_connection(replace(settings, smtp_port=port, smtp_security="tls", **overrides))
            assert events == []
    with smtp_server(cert, key) as (port, _, _):
        with pytest.raises(smtplib.SMTPAuthenticationError):
            mail_transport.check_connection(replace(settings, smtp_port=port, smtp_password="wrong"))


def report_message(settings):
    settings.archive_dir.mkdir(exist_ok=True)
    (settings.archive_dir / "test.csv").write_text("name,value\nexample,42\n")
    config = {"name": "Isolated report", "timezone": "UTC", "formats": ["csv"]}
    run = {"id": "isolated-run", "report_id": "isolated-report", "period_start": "2026-10-01T00:00:00+00:00", "period_end": "2026-10-02T00:00:00+00:00"}
    return config, run, {"csv": "test.csv"}


@pytest.mark.parametrize("refused,expected", [((), "sent"), (("reject@example.com",), "partial_rejected")])
def test_real_report_message_envelope_and_partial_rejection(setup, refused, expected):
    settings, cert, key = setup
    config, run, files = report_message(settings)
    with smtp_server(cert, key, refused=refused) as (port, _, messages):
        status = service.send_mail(replace(settings, smtp_port=port), config, run, files, ["reader@example.com", "reject@example.com"], False)
        assert status == expected and len(messages) == 1
        message = BytesParser(policy=policy.default).parsebytes(messages[0])
        assert message["Date"] and message["Message-ID"]
        assert message["From"] == "reports@example.com"
        assert len(list(message.iter_attachments())) == 1


def test_tls_relay_without_auth_and_all_recipients_refused(setup):
    settings, cert, key = setup
    settings = replace(settings, smtp_user="", smtp_password="")
    config, run, files = report_message(settings)
    with smtp_server(cert, key, auth=False, refused=("reader@example.com",)) as (port, events, messages):
        assert mail_transport.check_connection(replace(settings, smtp_port=port))
        with pytest.raises(smtplib.SMTPRecipientsRefused):
            service.send_mail(replace(settings, smtp_port=port), config, run, files, ["reader@example.com"], False)
        assert not any(cmd == "AUTH" for cmd, _ in events)
        assert messages == []


def test_ambiguous_data_response_is_not_silently_successful(setup):
    settings, cert, key = setup
    config, run, files = report_message(settings)
    with smtp_server(cert, key, drop_after_data=True) as (port, _, messages):
        with pytest.raises(smtplib.SMTPServerDisconnected):
            service.send_mail(replace(settings, smtp_port=port), config, run, files, ["reader@example.com"], False)
        assert len(messages) == 1


def test_setup_failure_is_definitely_before_message_delivery(setup):
    settings, cert, key = setup
    config, run, files = report_message(settings)
    with smtp_server(cert, key, starttls=False) as (port, events, messages):
        with pytest.raises(service.MailSetupError):
            service.send_mail(replace(settings, smtp_port=port), config, run, files, ["reader@example.com"], False)
        assert messages == [] and not any(cmd == "MAIL" for cmd, _ in events)


@pytest.mark.parametrize(
    "refused,drop,expected",
    [
        (("reject@example.com",), False, "partial_rejected"),
        (("reader@example.com", "reject@example.com"), False, "failed"),
        ((), True, "unknown"),
    ],
)
def test_worker_records_delivery_without_replaying(setup, refused, drop, expected, caplog):
    from openreporting import db, dashboards, datasources, security

    settings, cert, key = setup
    settings = replace(settings, secret_key_file="", database_url="", ldap_enabled=False)
    db.init_db(settings)
    datasources.provision(settings)
    user = {"id": security.create_user(settings, "admin1", "isolated-local-password", "admin"), "role": "admin"}
    dashboards.save(
        settings,
        user,
        {
            "uid": "smtp-test",
            "title": "SMTP test",
            "panels": [{"id": 1, "type": "timeseries", "targets": [{"refId": "A", "datasource": {"uid": "testdata"}, "scenario": "sine"}]}],
        },
    )
    report = service.save_report(settings, user, {"name": "SMTP test", "dashboard_uid": "smtp-test", "formats": ["csv"]})
    with smtp_server(cert, key, refused=refused, drop_after_data=drop) as (port, _, messages):
        active = replace(settings, smtp_port=port)
        run_id = service.request_run(active, user, report["id"], {"recipients": ["reader@example.com", "reject@example.com"]})["run_id"]
        assert service.claim(active) == run_id
        service.execute(active, run_id)
        run = service.list_runs(active, report["id"])[0]
        assert (run["status"], run["delivery_status"]) == ("completed", expected)
        assert service.claim(active) is None
        assert len(messages) == (0 if expected == "failed" else 1)
    assert "isolated-smtp-password" not in caplog.text
