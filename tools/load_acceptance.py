"""Bounded, synthetic HTTP acceptance in a disposable application (never live data)."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import logging
import math
import os
from pathlib import Path
import platform
import secrets
import socket
import tempfile
import threading
import time

import httpx
import uvicorn

from openreporting import dashboards, security
from openreporting.config import Settings
from openreporting.frames import total_points
from openreporting.http_telemetry import log
from openreporting.web import create_app


def percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] * 1000, 3) if values else None


def run(users, seconds, series, points, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='openreporting-load-') as work:
        settings = Settings(data_dir=Path(work),secure_cookie=False,session_hours=1,max_rows=200000,query_timeout_ms=30000,
                            mail_enabled=False,smtp_host='',smtp_port=587,smtp_starttls=True,smtp_user='',smtp_password='',
                            smtp_from='',recipient_domains=(),provision_testdata=True)
        app = create_app(settings)
        password = secrets.token_urlsafe(32)
        admin = {'id':security.create_user(settings,'load_admin',password,'admin'),'role':'admin'}
        target = {'refId':'A','scenario':'sine','seriesCount':series,'amplitude':20,'datasource':{'uid':'testdata'}}
        dashboards.save(settings,admin,{'uid':'load-fixture','title':'Synthetic load fixture','panels':[
            {'id':1,'title':'Synthetic only','type':'timeseries','datasource':{'uid':'testdata'},'targets':[target]}]})
        for i in range(users):
            security.create_user(settings,f'load_viewer_{i}',password,'viewer')
        listener = socket.socket()
        listener.bind(('127.0.0.1',0))
        listener.listen(128)
        base = f'http://127.0.0.1:{listener.getsockname()[1]}'
        config = uvicorn.Config(app,host='127.0.0.1',port=0,access_log=False,log_level='warning',lifespan='on')
        server = uvicorn.Server(config)
        server_thread = threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True)
        handler = logging.FileHandler(output.with_suffix('.http.jsonl'),encoding='utf8',mode='w')
        handler.setFormatter(logging.Formatter('%(message)s'))
        previous = (log.level, log.propagate)
        log.addHandler(handler);log.setLevel(logging.INFO);log.propagate=False
        clients = []
        server_thread.start()
        payload = {'targets':[target],'dashboardUid':'load-fixture','panelId':1,'range':{'from':'now-6h','to':'now'},
                   'timezone':'UTC','maxDataPoints':points}
        try:
            deadline = time.monotonic() + 20
            while not server.started:
                if time.monotonic()>deadline or not server_thread.is_alive():
                    raise RuntimeError('Isolated HTTP server did not start')
                time.sleep(.02)
            warmup_points = None
            for i in range(users):
                client = httpx.Client(base_url=base,timeout=35,trust_env=False)
                clients.append(client)
                response = client.post('/api/login',json={'username':f'load_viewer_{i}','password':password})
                assert response.status_code==200,'Synthetic login failed'
                client.headers['X-CSRF-Token'] = response.json()['csrf']
                response = client.post('/api/ds/query',json=payload)
                assert response.status_code==200 and not any(r.get('error') for r in response.json()['results'].values())
                warmup_points = total_points(response.json()['frames'])
                assert warmup_points>0,'No synthetic data returned'
            started = time.perf_counter()
            until = started + seconds

            def exercise(client):
                rows = []
                index = 0
                while time.perf_counter()<until:
                    kind = ['query','query','dashboard','health','query'][index % 5]
                    tick = time.perf_counter()
                    try:
                        response = client.post('/api/ds/query',json=payload) if kind=='query' else client.get(
                            '/api/dashboards/uid/load-fixture' if kind=='dashboard' else '/api/health')
                        code = str(response.status_code)
                        good = response.status_code==200 and bool(response.headers.get('x-request-id'))
                        if kind=='query' and good:
                            data = response.json()
                            good = bool(data['frames']) and not data.get('transformError') and not any(
                                r.get('error') for r in data['results'].values())
                    except (httpx.HTTPError,ValueError,KeyError):
                        code,good = 'client_error',False
                    rows.append((kind,time.perf_counter()-tick,code,good))
                    index += 1
                return rows

            with ThreadPoolExecutor(max_workers=users) as pool:
                futures = [pool.submit(exercise,client) for client in clients]
                rows = [row for future in futures for row in future.result()]
            elapsed = time.perf_counter()-started
            groups = defaultdict(list)
            for kind,duration,_code,_good in rows:
                groups[kind].append(duration)
            report = {'timestamp_utc':datetime.now(timezone.utc).isoformat(),'synthetic_only':True,
                      'source_sha256':{name:hashlib.sha256((Path(__file__).resolve().parents[1] / name).read_bytes()).hexdigest()
                                       for name in ['openreporting/http_telemetry.py','openreporting/web.py','tools/load_acceptance.py']},
                      'environment':{'os':platform.system(),'python':platform.python_version(),'cpu_count':os.cpu_count(),
                                     'packages':{name:version(name) for name in ['fastapi','starlette','uvicorn','httpx']},
                                     'web_processes':1,'database':'temporary SQLite','network':'real loopback HTTP',
                                     'structured_log':'file','report_worker':False},
                      'workload':{'concurrent_viewers':users,'requested_seconds':seconds,'elapsed_seconds':round(elapsed,3),
                                  'series_per_query':series,'max_data_points':points,'warmup_returned_points':warmup_points,
                                  'route_mix':['query','query','dashboard','health','query']},
                      'requests':len(rows),'errors':sum(not row[3] for row in rows),
                      'status_counts':dict(Counter(row[2] for row in rows)),
                      'requests_per_second':round(len(rows)/elapsed,3),
                      'latency_ms':{kind:{'count':len(values),'p50':percentile(values,.5),'p95':percentile(values,.95),
                                          'p99':percentile(values,.99),'max':round(max(values)*1000,3)} for kind,values in groups.items()},
                      'limits':['Closed-loop synthetic read workload; not a production capacity promise',
                                'No real source network, nginx/TLS, LDAP/SMTP or concurrent report worker',
                                'No overnight soak, browser rendering or memory leak measurement']}
            output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
            print(json.dumps(report,indent=2))
            assert report['errors']==0,'Synthetic workload produced errors; see sanitized evidence'
        finally:
            for client in clients:
                client.close()
            server.should_exit = True
            server_thread.join(timeout=15)
            listener.close()
            log.removeHandler(handler);handler.close()
            log.setLevel(previous[0]);log.propagate=previous[1]
            assert not server_thread.is_alive(),'Isolated server did not exit cleanly'


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--users',type=int,default=8)
    parser.add_argument('--seconds',type=int,default=30)
    parser.add_argument('--series',type=int,default=8)
    parser.add_argument('--points',type=int,default=360)
    parser.add_argument('--output',type=Path,default=Path('build/load-acceptance.json'))
    args = parser.parse_args()
    if not (1<=args.users<=32 and 1<=args.seconds<=300 and 1<=args.series<=50 and 10<=args.points<=20000):
        parser.error('Bounded limits: users 1..32, seconds 1..300, series 1..50, points 10..20000')
    run(args.users,args.seconds,args.series,args.points,args.output)
