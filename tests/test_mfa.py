"""Isolated second-factor acceptance: no live users, directory or mail credentials."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json

from fastapi.testclient import TestClient
import pyotp
import pytest

from openreporting import db,mfa,security
from openreporting.config import Settings
from openreporting.secrets_store import decrypt,key_path,reset_cache
from openreporting.web import create_app

PASSWORD = 'isolated-factor-password'
NOW = 1800000000


@pytest.fixture
def state(tmp_path,monkeypatch):
    settings = replace(Settings.from_env(),data_dir=tmp_path / 'data',database_url='',secret_key_file='',secure_cookie=True,
                       ldap_enabled=False,mail_enabled=False,mfa_required_roles=(),zabbix_token_file='',zabbix_url='')
    app = create_app(settings)
    uid = security.create_user(settings,'factoruser',PASSWORD,'admin')
    monkeypatch.setattr(mfa,'now_seconds',lambda:NOW)
    return settings,app,uid


def signin(client,code=None):
    return client.post('/api/login',json={'username':'factoruser','password':PASSWORD,'otp':code})


def enroll(client):
    signed = signin(client);assert signed.status_code==200
    headers = {'X-CSRF-Token':signed.json()['csrf']}
    started = client.post('/api/user/mfa/setup',json={'password':PASSWORD},headers=headers)
    assert started.status_code==200,started.text
    data = started.json()
    # Enrollment QR encodes exactly the otpauth URI for this secret (rendered server-side as SVG).
    from urllib.parse import parse_qs, urlsplit
    from openreporting.mfa import qr_data_uri
    uri = urlsplit(data['uri'])
    assert uri.scheme == 'otpauth' and uri.netloc == 'totp'
    assert parse_qs(uri.query) == {'secret': [data['secret']], 'issuer': ['OpenReporting']}
    assert data['qr'].startswith('data:image/svg+xml') and data['qr'] == qr_data_uri(data['uri'])
    confirmed = client.post('/api/user/mfa/confirm',json={'password':PASSWORD,'code':pyotp.TOTP(data['secret']).at(NOW),
                           'setup_token':data['setup_token']},headers=headers)
    assert confirmed.status_code==200,confirmed.text
    return data['secret'],confirmed.json()['recovery_codes']


@pytest.mark.parametrize('timestamp,expected',[(59,'94287082'),(1111111109,'07081804'),(1111111111,'14050471'),
    (1234567890,'89005924'),(2000000000,'69279037'),(20000000000,'65353130')])
def test_rfc6238_sha1_vectors(timestamp,expected):
    assert pyotp.TOTP('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ',digits=8).at(timestamp)==expected


def test_enable_revoke_primary_and_factor_required_recovery_is_one_use(state):
    settings,app,uid = state
    with TestClient(app,base_url='https://localhost') as client,TestClient(app,base_url='https://localhost') as other:
        assert signin(other).status_code==200
        secret,codes = enroll(client)
        assert len(codes)==10 and len(set(codes))==10
        assert client.get('/api/user').status_code==401 and other.get('/api/user').status_code==401
        missing = signin(client)
        assert missing.status_code==401 and missing.json()['detail']['code']=='mfa_required'
        assert client.post('/api/login',json={'username':'factoruser','password':'wrong','otp':codes[0]}).status_code==401
        assert signin(client,pyotp.TOTP(secret).at(NOW)).status_code==401  # enrollment code already consumed
        assert signin(client,pyotp.TOTP(secret).at(NOW+30)).status_code==200
        assert client.get('/api/user').status_code==200
        assert signin(other,pyotp.TOTP(secret).at(NOW+30)).status_code==401
        assert signin(other,codes[0]).status_code==200
        assert signin(client,codes[0]).status_code==401
        status = other.get('/api/user/mfa').json()
        assert status=={'enabled':True,'recovery_remaining':9,'required':False}
        with db.connect(settings) as conn:
            row = mfa.factor(conn,uid)
            assert secret not in row['secret_json']
            assert decrypt(settings,row['secret_json'])['user_id']==uid
            assert all(code not in row['recovery_hashes'] for code in codes)
            audit = '\n'.join(str(tuple(r)) for r in conn.execute('SELECT * FROM audit'))
            assert secret not in audit and all(code not in audit for code in codes)
            assert db.verify_audit(conn)==(True,None)


def test_required_role_enrollment_session_denies_business_routes_and_expires(state):
    settings,_,uid = state
    required = replace(settings,mfa_required_roles=('admin',))
    with TestClient(create_app(required),base_url='https://localhost') as client:
        signed = signin(client);assert signed.status_code==200
        assert client.get('/api/session').json()['mfa_enrollment_required'] is True
        for path in ('/api/user','/api/search','/api/datasources','/api/admin/stats','/api/frontend/settings','/api/dash-reports'):
            assert client.get(path).status_code==403,path
        assert client.post('/api/ds/query',json={}).status_code==403
        assert client.get('/api/user/mfa').json()['required'] is True
        assert client.post('/api/user/mfa/setup',json={'password':PASSWORD}).status_code==403
        secret,codes = enroll(client)
        signed = signin(client,codes[0]);assert signed.status_code==200
        assert client.get('/api/session').json()['mfa_enrollment_required'] is False
        assert client.get('/api/user').status_code==200
    # Already enabled factors remain enforced if an operator removes the policy.
    with TestClient(create_app(settings),base_url='https://localhost') as client:
        assert signin(client).status_code==401
    mfa.admin_reset(settings,'factoruser','lost-device')
    with TestClient(create_app(required),base_url='https://localhost') as client:
        assert signin(client).status_code==200
        with db.connect(settings) as conn,db.transaction(conn):
            conn.execute('UPDATE sessions SET created_at=?',((datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat(),))
        assert client.get('/api/session').status_code==401


def test_pending_expiry_token_replacement_stepup_and_rate_limit(state):
    settings,app,uid = state
    with TestClient(app,base_url='https://localhost') as client:
        response = signin(client);headers={'X-CSRF-Token':response.json()['csrf']}
        first = client.post('/api/user/mfa/setup',json={'password':PASSWORD},headers=headers).json()
        second = client.post('/api/user/mfa/setup',json={'password':PASSWORD},headers=headers).json()
        body = {'password':PASSWORD,'code':pyotp.TOTP(second['secret']).at(NOW),'setup_token':first['setup_token']}
        assert client.post('/api/user/mfa/confirm',json=body,headers=headers).status_code==409
        body['setup_token']=second['setup_token']
        with db.connect(settings) as conn,db.transaction(conn):
            conn.execute("UPDATE user_mfa SET pending_expires_at='2000-01-01T00:00:00+00:00'")
        assert client.post('/api/user/mfa/confirm',json=body,headers=headers).status_code==409
        third=client.post('/api/user/mfa/setup',json={'password':PASSWORD},headers=headers).json()
        body.update(setup_token=third['setup_token'],code='not-a-code')
        for _ in range(5):
            assert client.post('/api/user/mfa/confirm',json=body,headers=headers).status_code==403
        assert client.post('/api/user/mfa/setup',json={'password':PASSWORD},headers=headers).status_code==429
        with db.connect(settings) as conn:
            assert conn.execute('SELECT count FROM login_failures').fetchone()[0]==5


def test_disable_and_rotate_require_password_fresh_factor_and_revoke(state):
    settings,app,uid = state
    with TestClient(app,base_url='https://localhost') as client:
        secret,codes=enroll(client)
        signed=signin(client,codes[0]);headers={'X-CSRF-Token':signed.json()['csrf']}
        assert client.post('/api/user/mfa/recovery',json={'password':'wrong','code':codes[1]},headers=headers).status_code==403
        rotated=client.post('/api/user/mfa/recovery',json={'password':PASSWORD,'code':codes[1]},headers=headers)
        assert rotated.status_code==200
        assert client.get('/api/user').status_code==401
        assert signin(client,codes[2]).status_code==401
        new=rotated.json()['recovery_codes']
        signed=signin(client,new[0]);headers={'X-CSRF-Token':signed.json()['csrf']}
        disabled=client.post('/api/user/mfa/disable',json={'password':PASSWORD,'code':new[1]},headers=headers)
        assert disabled.status_code==200 and disabled.json()['enabled'] is False
        assert client.get('/api/user').status_code==401
        assert signin(client).status_code==200


def test_same_factor_or_recovery_cannot_succeed_twice_in_parallel(state):
    settings,app,uid=state
    with TestClient(app,base_url='https://localhost') as client:
        secret,codes=enroll(client)
    for code in (pyotp.TOTP(secret).at(NOW+30),codes[0]):
        def consume(_):
            with db.connect(settings) as conn,db.transaction(conn):
                return mfa.consume(conn,settings,uid,code)
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(consume,range(2)))==[False,True]


def test_seed_binding_missing_key_and_operator_reset_preserve_password(state):
    settings,app,uid=state
    with TestClient(app,base_url='https://localhost') as client:
        secret,codes=enroll(client)
        with db.connect(settings) as conn:
            before=conn.execute('SELECT password_hash FROM users WHERE id=?',(uid,)).fetchone()[0]
            row=dict(mfa.factor(conn,uid))
        row['user_id']='different-user'
        with pytest.raises(mfa.Unavailable):mfa.seed(settings,row)
        saved=key_path(settings).read_bytes();key_path(settings).unlink()  # owned temp fixture only
        reset_cache()  # model a fresh service, not its already-loaded in-memory key
        assert signin(client,pyotp.TOTP(secret).at(NOW+30)).status_code==503
        assert not key_path(settings).exists()  # never replace a lost key
        key_path(settings).write_bytes(saved)
        assert mfa.admin_reset(settings,'factoruser','recovery')['reset']
        assert signin(client).status_code==200
        with db.connect(settings) as conn:
            assert conn.execute('SELECT password_hash FROM users WHERE id=?',(uid,)).fetchone()[0]==before
            assert db.verify_audit(conn)==(True,None)


def test_transport_and_non_loopback_cannot_send_factor_over_http(state):
    settings,app,uid=state
    insecure=replace(settings,secure_cookie=False)
    with TestClient(create_app(insecure),base_url='http://localhost') as client:
        signed=signin(client);headers={'X-CSRF-Token':signed.json()['csrf']}
        assert client.post('/api/user/mfa/setup',json={'password':PASSWORD},headers=headers).status_code==400
        assert signin(client,'123456').status_code==400


def test_existing_session_is_restricted_when_role_policy_is_enabled(state):
    settings,app,uid=state
    with TestClient(app,base_url='https://localhost') as old:
        assert signin(old).status_code==200
        token=old.cookies.get('openreporting_session')
    with TestClient(create_app(replace(settings,mfa_required_roles=('admin',))),base_url='https://localhost') as client:
        client.cookies.set('openreporting_session',token)
        assert client.get('/api/user').status_code==403
        assert client.get('/api/session').json()['mfa_enrollment_required']


def test_password_reset_never_removes_factor_or_consumes_recovery(state):
    settings,app,uid=state
    with TestClient(app,base_url='https://localhost') as client:
        secret,codes=enroll(client)
        with db.connect(settings) as conn,db.transaction(conn):
            conn.execute('UPDATE users SET password_hash=? WHERE id=?',(security.password_hash('new-isolated-password'),uid))
            conn.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
        assert client.post('/api/login',json={'username':'factoruser','password':'new-isolated-password'}).status_code==401
        assert client.post('/api/login',json={'username':'factoruser','password':'new-isolated-password','otp':codes[0]}).status_code==200


def test_ldap_stepup_is_bound_to_same_identity_and_role(state,monkeypatch):
    from openreporting import directory_auth
    settings,_,_=state
    settings=replace(settings,ldap_enabled=True)
    identity=directory_auth.Identity('synthetic-stable-directory-id','editor')
    monkeypatch.setattr(directory_auth,'authenticate',lambda *args:identity)
    with TestClient(create_app(settings),base_url='https://localhost') as client:
        signed=client.post('/api/login',json={'username':'directoryuser','password':PASSWORD})
        headers={'X-CSRF-Token':signed.json()['csrf']}
        endpoint='/api/user/mfa/setup'
        identity=replace(identity,subject='different-id')
        assert client.post(endpoint,json={'password':PASSWORD},headers=headers).status_code==403
        identity=replace(identity,subject='synthetic-stable-directory-id',role='admin')
        assert client.post(endpoint,json={'password':PASSWORD},headers=headers).status_code==403
        identity=replace(identity,role='editor')
        started=client.post(endpoint,json={'password':PASSWORD},headers=headers)
        assert started.status_code==200
        data=started.json()
        confirmed=client.post('/api/user/mfa/confirm',json={'password':PASSWORD,'setup_token':data['setup_token'],
                              'code':pyotp.TOTP(data['secret']).at(NOW)},headers=headers)
        assert confirmed.status_code==200
        assert client.post('/api/login',json={'username':'directoryuser','password':PASSWORD}).status_code==401
        assert client.post('/api/login',json={'username':'directoryuser','password':PASSWORD,'otp':confirmed.json()['recovery_codes'][0]}).status_code==200
        identity=replace(identity,role='viewer')
        assert client.post('/api/login',json={'username':'directoryuser','password':PASSWORD}).json()['detail']['code']=='mfa_required'
        assert client.get('/api/user').status_code==401  # role reduction commits even before factor response


def test_upgrade_v3_preserves_users_sessions_and_source_data(tmp_path,monkeypatch):
    settings=replace(Settings.from_env(),data_dir=tmp_path,database_url='',secret_key_file='',ldap_enabled=False,mfa_required_roles=())
    with monkeypatch.context() as patch:
        patch.setattr(db,'CURRENT_VERSION',3)
        db.init_db(settings)
        uid=security.create_user(settings,'migrateuser',PASSWORD)
        with db.connect(settings) as conn,db.transaction(conn):
            conn.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',('opaque-hash',uid,'csrf-hash','2100-01-01T00:00:00+00:00',db.utcnow()))
            before=tuple(conn.execute('SELECT * FROM users').fetchone())
    db.init_db(settings)
    with db.connect(settings) as conn:
        assert db.schema_version(conn)==db.CURRENT_VERSION
        assert tuple(conn.execute('SELECT * FROM users').fetchone())==before
        assert conn.execute('SELECT token_hash FROM sessions').fetchone()[0]=='opaque-hash'
        assert conn.execute('SELECT COUNT(*) FROM user_mfa').fetchone()[0]==0
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_factor_survives_rekey_retirement_and_verified_backup_restore(state,tmp_path):
    import hashlib
    import shutil
    import tarfile
    from openreporting import key_rotation
    from openreporting.backup_verify import verify_backup
    settings,app,uid=state
    with TestClient(app,base_url='https://localhost') as client:
        secret,codes=enroll(client)
    ring=tmp_path / 'staged-ring.json'
    key_rotation.prepare_rotation(settings,ring)
    rotated=replace(settings,secret_key_file=str(ring))
    result=key_rotation.rekey_secrets(rotated,services_stopped=True)
    assert result['mfa_secrets_rekeyed']==1
    primary=tmp_path / 'primary.json'
    key_rotation.prepare_retirement(rotated,primary,services_stopped=True)
    rotated=replace(settings,secret_key_file=str(primary))
    with db.connect(rotated) as conn:
        assert mfa.seed(rotated,mfa.factor(conn,uid))==secret
    target=tmp_path / 'bundle';target.mkdir()
    db.backup_database(rotated,target / 'state.sqlite3')
    with tarfile.open(target / 'archive.tar.gz','w:gz') as archive:
        archive.add(settings.archive_dir,arcname='archive')
    (target / 'openreporting.env').write_text('OPENREPORTING_MAIL_ENABLED=false\n')
    (target / 'SHA256SUMS').write_text('\n'.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  ./'+p.name for p in target.iterdir() if p.name!='SHA256SUMS')+'\n')
    assert verify_backup(target,key_file=primary)['encrypted_factors']==1
    restored_dir=tmp_path / 'restored';restored_dir.mkdir()
    shutil.copyfile(target / 'state.sqlite3',restored_dir / 'state.sqlite3')
    restored=replace(rotated,data_dir=restored_dir,provision_testdata=False)
    with TestClient(create_app(restored),base_url='https://localhost') as client:
        assert signin(client).status_code==401
        assert signin(client,pyotp.TOTP(secret).at(NOW+30)).status_code==200
        assert signin(client,codes[0]).status_code==200


def test_rekey_rolls_back_all_factors_if_bound_seed_is_corrupt(state,tmp_path):
    from openreporting import key_rotation
    from openreporting.secrets_store import encrypt,SecretError
    settings,app,uid=state
    with TestClient(app,base_url='https://localhost') as client:
        enroll(client)
    ring=tmp_path / 'ring.json';key_rotation.prepare_rotation(settings,ring)
    with db.connect(settings) as conn,db.transaction(conn):
        conn.execute('UPDATE user_mfa SET secret_json=?',(encrypt(settings,{'type':'mfa-totp-v1','user_id':'wrong-id','secret':'A'*32}),))
    with db.connect(settings) as conn:
        before=conn.execute('SELECT secret_json FROM user_mfa').fetchone()[0]
    with pytest.raises(SecretError):
        key_rotation.rekey_secrets(replace(settings,secret_key_file=str(ring)),services_stopped=True)
    with db.connect(settings) as conn:
        assert conn.execute('SELECT secret_json FROM user_mfa').fetchone()[0]==before


def test_configuration_rejects_unknown_required_roles(monkeypatch):
    monkeypatch.setenv('OPENREPORTING_MFA_REQUIRED_ROLES','admin,unknown-role')
    with pytest.raises(ValueError,match='MFA required role policy'):Settings.from_env()


def test_active_factor_failures_cannot_be_reset_by_password_only_challenges(state):
    settings,app,uid=state
    with TestClient(app,base_url='https://localhost') as client:
        _,codes=enroll(client)
        for attempt in range(5):
            # A valid password without a factor must not clear previous failed proofs.
            challenge=signin(client)
            assert challenge.status_code==401 and challenge.json()['detail']['code']=='mfa_required'
            assert signin(client,'invalid-factor-proof').status_code==401
            with db.connect(settings) as conn:
                assert conn.execute('SELECT count FROM login_failures').fetchone()[0]==attempt+1
                assert conn.execute('SELECT count(*) FROM sessions WHERE user_id=?',(uid,)).fetchone()[0]==0
        assert signin(client).status_code==429
        assert signin(client,codes[0]).status_code==429
        with db.connect(settings) as conn,db.transaction(conn):
            assert len(mfa.recovery_hashes(mfa.factor(conn,uid)))==10  # locked request cannot consume recovery
            conn.execute('UPDATE login_failures SET last_at=?',((datetime.now(timezone.utc)-timedelta(minutes=16)).isoformat(),))
        assert signin(client,codes[0]).status_code==200
        with db.connect(settings) as conn:
            assert conn.execute('SELECT count(*) FROM login_failures').fetchone()[0]==0
            assert len(mfa.recovery_hashes(mfa.factor(conn,uid)))==9


def test_operator_reset_never_bootstraps_a_missing_or_migrates_an_old_store(tmp_path,monkeypatch):
    settings=replace(Settings.from_env(),data_dir=tmp_path,database_url='',mfa_required_roles=())
    with pytest.raises(ValueError,match='Existing application database'):
        mfa.admin_reset(settings,'missing','recovery')
    assert not settings.db_path.exists()
    with monkeypatch.context() as patch:
        patch.setattr(db,'CURRENT_VERSION',3)
        db.init_db(settings)
    with pytest.raises(ValueError,match='Matching application schema'):
        mfa.admin_reset(settings,'missing','recovery')
    with db.connect(settings) as conn:
        assert db.schema_version(conn)==3


def test_enrollment_tolerates_one_step_clock_skew_but_rejects_drift_and_setup_key(state):
    # Phone clocks up to 30 s off still enroll; larger drift, wrong codes and the setup key itself do not.
    settings,app,uid = state
    with TestClient(app,base_url='https://localhost') as client:
        signed = signin(client);assert signed.status_code==200
        headers = {'X-CSRF-Token':signed.json()['csrf']}
        data = client.post('/api/user/mfa/setup',json={'password':PASSWORD},headers=headers).json()
        otp = pyotp.TOTP(data['secret'])
        def confirm(code):
            return client.post('/api/user/mfa/confirm',json={'password':PASSWORD,'code':code,'setup_token':data['setup_token']},headers=headers)
        for wrong in (otp.at(NOW-90),otp.at(NOW+90),data['secret']):
            assert confirm(wrong).status_code==403
        assert confirm(otp.at(NOW-30)).status_code==200
