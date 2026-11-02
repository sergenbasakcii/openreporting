"""Kubernetes acceptance through the real ingress (stdlib only; run by deploy/kubernetes/ci-kind.sh).

phase1          sign in, secure cookie, HTTPS-only MFA, shared sessions/settings across web pods,
                worker heartbeat, report rendered by the worker and downloaded from every web pod
active-worker   print the heartbeat owner
failover ID     wait until a different worker owns the heartbeat
phase2          after a web rolling restart: the stored session and archive are still served
"""
import hashlib
import http.cookiejar
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ['OPENREPORTING_K8S_URL']
PASSWORD = os.environ['OPENREPORTING_K8S_PASSWORD']
STATE = os.path.join(os.path.dirname(os.environ['OPENREPORTING_K8S_CA']), 'acceptance-state.json')
JAR_FILE = os.path.join(os.path.dirname(os.environ['OPENREPORTING_K8S_CA']), 'acceptance-cookies.txt')
CONTEXT = ssl.create_default_context(cafile=os.environ['OPENREPORTING_K8S_CA'])
jar = http.cookiejar.MozillaCookieJar(JAR_FILE)
if os.path.exists(JAR_FILE):
    jar.load(ignore_discard=True)
opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=CONTEXT), urllib.request.HTTPCookieProcessor(jar))
csrf = ''


def call(method, path, body=None, *, raw=False, expect=200):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header('Origin', BASE)
    if data is not None:
        request.add_header('Content-Type', 'application/json')
    if csrf:
        request.add_header('X-CSRF-Token', csrf)
    try:
        with opener.open(request, timeout=60) as response:
            status, headers, payload = response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        status, headers, payload = exc.code, exc.headers, exc.read()
    if status != expect:
        raise AssertionError(f'{method} {path}: HTTP {status} {payload[:300]!r}')
    return (payload, headers) if raw else json.loads(payload or b'null')


def login():
    global csrf
    csrf = ''
    payload, headers = call('POST', '/api/login', {'username': 'k8sadmin', 'password': PASSWORD}, raw=True)
    cookies = headers.get_all('Set-Cookie') or []
    assert any(c.startswith('openreporting_session=') and 'secure' in c.lower() for c in cookies), 'Secure session cookie'
    csrf = json.loads(payload)['csrf']
    jar.save(ignore_discard=True)


def wait_for(predicate, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(3)
    raise AssertionError(message)


def worker():
    return call('GET', '/api/admin/stats')['worker']


def phase1():
    login()
    # Refused over plain HTTP: success proves the ingress's X-Forwarded-Proto is trusted.
    assert call('POST', '/api/user/mfa/setup', {'password': PASSWORD})['qr'].startswith('data:image/svg+xml')
    for _ in range(20):  # spread over both web pods by the Service
        assert call('GET', '/api/user')['username'] == 'k8sadmin'
    revision = call('GET', '/api/admin/settings')['scopes']['security']['revision']
    call('PUT', '/api/admin/settings/security', {'revision': revision, 'values': {'session_hours': 6}, 'secrets': {}, 'password': PASSWORD})
    time.sleep(3)  # other processes re-read the settings revision within CHECK_INTERVAL_S
    assert all(call('GET', '/api/admin/settings')['scopes']['security']['fields']['session_hours']['value'] == 6 for _ in range(10))
    wait_for(lambda: worker()['state'] == 'up', 120, 'worker heartbeat')
    call('POST', '/api/dashboards/db', {'overwrite': True, 'dashboard': {'uid': 'k8s', 'title': 'K8s acceptance', 'panels': [
        {'id': 1, 'type': 'timeseries', 'gridPos': {'x': 0, 'y': 0, 'w': 24, 'h': 8},
         'targets': [{'refId': 'A', 'datasource': {'uid': 'testdata'}, 'scenario': 'sine'}]}]}})
    report = call('POST', '/api/dash-reports', {'name': 'K8s acceptance report', 'dashboard_uid': 'k8s', 'formats': ['csv', 'pdf']}, expect=201)
    run_id = call('POST', f"/api/dash-reports/{report['id']}/runs", {})['run_id']

    def finished():
        run = next(r for r in call('GET', f"/api/dash-reports/{report['id']}/runs") if r['id'] == run_id)
        assert run['status'] not in ('failed', 'blocked', 'needs_review'), run
        return run if run['status'] == 'completed' else None
    wait_for(finished, 180, 'report run completed')
    digests = {hashlib.sha256(call('GET', f'/api/report-runs/{run_id}/files/csv', raw=True)[0]).hexdigest() for _ in range(10)}
    assert len(digests) == 1, 'every web pod serves the same archived file'
    with open(STATE, 'w', encoding='utf-8') as handle:
        json.dump({'csrf': csrf, 'run_id': run_id, 'digest': digests.pop()}, handle)
    return {'ok': True, 'run_id': run_id, 'worker': worker()['state']}


def phase2():
    global csrf
    with open(STATE, encoding='utf-8') as handle:
        state = json.load(handle)
    csrf = state['csrf']
    assert call('GET', '/api/user')['username'] == 'k8sadmin'  # session survived replacing every web pod
    body = call('GET', f"/api/report-runs/{state['run_id']}/files/csv", raw=True)[0]
    assert hashlib.sha256(body).hexdigest() == state['digest']
    assert call('GET', '/api/admin/settings')['scopes']['security']['fields']['session_hours']['value'] == 6
    return {'ok': True}


def failover(previous):
    global csrf
    with open(STATE, encoding='utf-8') as handle:
        csrf = json.load(handle)['csrf']
    owner = wait_for(lambda: (w := worker())['state'] == 'up' and w.get('worker_id') not in (None, previous) and w, 150,
                     'standby worker took over')
    return {'ok': True, 'previous': previous, 'current': owner['worker_id']}


if __name__ == '__main__':
    action = sys.argv[1]
    if action == 'active-worker':
        with open(STATE, encoding='utf-8') as handle:
            csrf = json.load(handle)['csrf']
        print(worker()['worker_id'])
    else:
        result = {'phase1': phase1, 'phase2': phase2}[action]() if action != 'failover' else failover(sys.argv[2])
        print(json.dumps(result))
