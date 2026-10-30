"""Own an ephemeral loopback test application; never use a configured/live data store."""
from dataclasses import replace
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time

import uvicorn

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from openreporting.config import Settings
from openreporting.security import create_user
from openreporting.web import create_app


def main():
    with tempfile.TemporaryDirectory(prefix='openreporting-mfa-browser-') as work:
        settings=Settings(data_dir=Path(work),secure_cookie=False,session_hours=1,max_rows=200000,query_timeout_ms=30000,
                          mail_enabled=False,smtp_host='',smtp_port=587,smtp_starttls=True,smtp_user='',smtp_password='',
                          smtp_from='',recipient_domains=(),mfa_required_roles=('admin',))
        app=create_app(settings)
        password=secrets.token_urlsafe(32)
        create_user(settings,'optionaluser',password,'viewer')
        create_user(settings,'requireduser',password,'admin')
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
        server=uvicorn.Server(uvicorn.Config(app,access_log=False,log_level='warning',lifespan='on'))
        thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True)
        thread.start()
        try:
            deadline=time.monotonic()+20
            while not server.started:
                if time.monotonic()>deadline or not thread.is_alive():raise RuntimeError('Disposable fixture failed to start')
                time.sleep(.02)
            env=dict(os.environ,OPENREPORTING_MFA_DISPOSABLE='true',UI_TEST_PASSWORD=password,
                     OPENREPORTING_UI_URL=f'http://127.0.0.1:{listener.getsockname()[1]}')
            subprocess.run(['node','tests/browser/mfa-flow.cjs'],env=env,check=True,timeout=240)
        finally:
            server.should_exit=True
            thread.join(timeout=15)
            listener.close()
            if thread.is_alive():raise RuntimeError('Disposable fixture did not stop')


if __name__=='__main__':main()
