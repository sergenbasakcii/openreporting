"""Full, non-destructive recovery acceptance including archive, logo and old secrets."""
import base64
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from openreporting import dashboards, datasources, db, security
from openreporting import folder_access
from openreporting.backup_verify import BackupVerificationError, verify_backup, _unpack
from openreporting.config import Settings
from openreporting.reporting import logos, service
from openreporting.secrets_store import encrypt
from openreporting.web import create_app


def checksum(directory):
    lines = [hashlib.sha256(p.read_bytes()).hexdigest()+'  ./'+p.name for p in sorted(directory.iterdir()) if p.name!='SHA256SUMS']
    (directory / 'SHA256SUMS').write_text('\n'.join(lines)+'\n',encoding='ascii')


@pytest.fixture
def bundle(tmp_path):
    settings = replace(Settings.from_env(),data_dir=tmp_path / 'live',database_url='',secret_key_file='',
                       ldap_enabled=False,mail_enabled=False,zabbix_url='',zabbix_token_file='')
    db.init_db(settings)
    datasources.provision(settings)
    user = {'id':security.create_user(settings,'admin1','isolated-restore-password','admin'),'role':'admin'}
    image = Image.new('RGB',(20,20),'blue'); image_data = io.BytesIO(); image.save(image_data,format='PNG')
    logo = logos.save(settings,base64.b64encode(image_data.getvalue()).decode())
    secured = encrypt(settings,{'token':'isolated-backup-secret'})
    with db.connect(settings) as connection,db.transaction(connection):
        connection.execute("UPDATE datasources SET secure_json=? WHERE uid='testdata'",(secured,))
        db.audit(connection,'test','source.secret_seeded','datasource','testdata')
    dashboards.save(settings,user,{'uid':'recovery','title':'Recovery test','panels':[
        {'id':1,'type':'timeseries','targets':[{'refId':'A','datasource':{'uid':'testdata'},'scenario':'sine'}]}]})
    report = service.save_report(settings,user,{'name':'Recovery report','dashboard_uid':'recovery','formats':['csv'],'logo_id':logo['id']})
    run_id = service.request_run(settings,user,report['id'],{})['run_id']
    assert service.claim(settings)==run_id
    service.execute(settings,run_id)
    assert service.list_runs(settings,report['id'])[0]['status']=='completed'
    target = tmp_path / 'backup';target.mkdir()
    db.backup_database(settings,target / 'state.sqlite3')
    with tarfile.open(target / 'archive.tar.gz','w:gz') as archive:
        archive.add(settings.archive_dir,arcname='archive')
        archive.add(settings.data_dir / 'logos',arcname='logos')
    (target / 'openreporting.env').write_text('OPENREPORTING_MAIL_ENABLED=false\n')
    checksum(target)
    return settings,target


def test_full_restore_check_preserves_live_and_backup_files(bundle):
    settings,backup = bundle
    original = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.iterdir()}
    result = verify_backup(backup,key_file=settings.data_dir / 'secret.key',require_logos=True)
    assert result == {'ok':True,'schema_version':db.CURRENT_VERSION,'reports':1,'artifacts':1,'logos':1,'encrypted_sources':1,'encrypted_factors':0}
    assert {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.iterdir()} == original
    with db.connect(settings) as connection:
        assert db.verify_audit(connection)==(True,None)
        assert security.check_password('isolated-restore-password',connection.execute("SELECT password_hash FROM users WHERE username='admin1'").fetchone()[0])


@pytest.mark.parametrize('table', ['folder_policy', 'folder_user_grants'])
def test_missing_authorization_table_is_not_a_valid_current_schema_backup(bundle, table):
    import sqlite3
    settings, backup = bundle
    # A recomputed file checksum cannot make an incomplete application schema valid.
    with sqlite3.connect(backup / 'state.sqlite3') as connection:
        connection.execute('DROP TABLE ' + table)  # fixed parameterized test inventory only
    checksum(backup)
    with pytest.raises(BackupVerificationError):
        verify_backup(backup, key_file=settings.data_dir / 'secret.key')


def test_private_folder_grants_and_archive_boundary_survive_verified_restore(bundle, tmp_path):
    settings, original = bundle
    with db.connect(settings) as connection:
        owner = dict(connection.execute("SELECT id,role FROM users WHERE username='admin1'").fetchone())
    viewer = {'id': security.create_user(settings, 'restoredviewer', 'isolated-folder-restore-password', 'viewer'), 'role': 'viewer'}
    folder = dashboards.save_folder(settings, owner, 'Recovery restricted')['uid']
    current = dashboards.get(settings, 'recovery', owner)['dashboard']
    dashboards.save(settings, owner, current, folder_uid=folder)
    folder_access.replace_policy(settings, owner, folder, {'restricted': True, 'revision': 0,
        'grants': [{'user_id': viewer['id'], 'permission': 'view'}]})
    backup = tmp_path / 'private-backup'; backup.mkdir()
    db.backup_database(settings, backup / 'state.sqlite3')
    shutil.copyfile(original / 'archive.tar.gz', backup / 'archive.tar.gz')
    shutil.copyfile(original / 'openreporting.env', backup / 'openreporting.env')
    checksum(backup)
    assert verify_backup(backup, key_file=settings.data_dir / 'secret.key')['ok']
    target = tmp_path / 'private-restored'; target.mkdir()
    shutil.copyfile(backup / 'state.sqlite3', target / 'state.sqlite3')
    shutil.copyfile(settings.data_dir / 'secret.key', target / 'secret.key')
    _unpack(backup / 'archive.tar.gz', target, 10_000_000)
    restored = replace(settings, data_dir=target, secret_key_file=str(target / 'secret.key'))
    assert folder_access.policy(restored, owner, folder)['restricted']
    assert folder_access.policy(restored, owner, folder)['grants'][0]['user_id'] == viewer['id']
    assert not dashboards.get(restored, 'recovery', viewer)['meta']['canEdit']
    report = service.list_reports(restored, viewer)[0]
    run = service.list_runs(restored, report['id'], user=viewer)[0]
    assert service.verified_file(restored, run['id'], 'csv', viewer)[0].is_file()
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        service.verified_file(restored, run['id'], 'csv')


def test_restored_application_login_archive_logo_and_new_worker_run(bundle,tmp_path):
    """A verified copy must also work through normal APIs and the report worker."""
    settings,backup = bundle
    verify_backup(backup,key_file=settings.data_dir / 'secret.key',require_logos=True)
    before = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.iterdir()}
    target = tmp_path / 'restored-application';target.mkdir()
    shutil.copyfile(backup / 'state.sqlite3',target / 'state.sqlite3')
    shutil.copyfile(settings.data_dir / 'secret.key',target / 'secret.key')
    _unpack(backup / 'archive.tar.gz',target,10_000_000)
    restored = replace(settings,data_dir=target,secret_key_file=str(target / 'secret.key'),
                       secure_cookie=False,provision_testdata=False)
    with TestClient(create_app(restored),base_url='http://localhost') as client:
        assert client.get('/api/health').status_code==200
        login = client.post('/api/login',json={'username':'admin1','password':'isolated-restore-password'})
        assert login.status_code==200
        headers = {'X-CSRF-Token':login.json()['csrf']}
        assert client.get('/readyz').status_code==200
        assert client.get('/api/dashboards/uid/recovery').status_code==200
        report = client.get('/api/dash-reports').json()[0]
        config = client.get('/api/dash-reports/'+report['id']).json()
        logo_id = config['config']['logo_id']
        image = client.get('/api/dash-reports/logos/'+logo_id)
        assert image.status_code==200 and image.content.startswith(b'\x89PNG')
        old_run = service.list_runs(restored,report['id'])[0]
        old_csv = client.get('/api/report-runs/'+old_run['id']+'/files/csv')
        assert old_csv.status_code==200 and old_csv.content
        response = client.post('/api/dash-reports/'+report['id']+'/runs',json={},headers=headers)
        assert response.status_code==200
        new_id = response.json()['run_id']
        assert service.claim(restored)==new_id
        service.execute(restored,new_id)
        new_run = service.list_runs(restored,report['id'])[0]
        assert new_run['status']=='completed'
        assert client.get('/api/report-runs/'+new_id+'/files/csv').status_code==200
        assert client.get('/readyz').status_code==200
    assert {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.iterdir()}==before
    assert len(service.list_runs(settings,report['id']))==1


def test_missing_or_wrong_key_is_not_replaced(bundle,tmp_path):
    _,backup = bundle
    with pytest.raises(BackupVerificationError,match='Encryption key is required'):
        verify_backup(backup)
    wrong = tmp_path / 'wrong-key';wrong.write_bytes(Fernet.generate_key())
    with pytest.raises(BackupVerificationError) as error:
        verify_backup(backup,key_file=wrong)
    assert 'isolated-backup-secret' not in str(error.value)
    assert not (backup / 'secret.key').exists()


def test_checksum_tampering_is_rejected_before_restore(bundle):
    _,backup = bundle
    with (backup / 'state.sqlite3').open('ab') as handle:
        handle.write(b'tamper')
    with pytest.raises(BackupVerificationError,match='checksum mismatch'):
        verify_backup(backup)


@pytest.mark.parametrize('member_name,kind',[('../outside',tarfile.REGTYPE),('archive/escape',tarfile.SYMTYPE),
                                          ('logos/CON',tarfile.REGTYPE),('/absolute',tarfile.REGTYPE)])
def test_unsafe_archive_never_writes_outside_verification_copy(bundle,tmp_path,member_name,kind):
    _,backup = bundle
    outside = tmp_path / 'outside';outside.write_text('keep')
    with tarfile.open(backup / 'archive.tar.gz','w:gz') as archive:
        info = tarfile.TarInfo(member_name);info.type=kind
        if kind==tarfile.SYMTYPE:info.linkname=str(outside)
        archive.addfile(info)
    checksum(backup)
    with pytest.raises(BackupVerificationError,match='Unsafe'):
        verify_backup(backup)
    assert outside.read_text()=='keep'


def test_missing_logo_in_otherwise_valid_backup_is_rejected(bundle):
    settings,backup = bundle
    with tarfile.open(backup / 'archive.tar.gz','w:gz') as archive:
        archive.add(settings.archive_dir,arcname='archive')
    checksum(backup)
    with pytest.raises(BackupVerificationError):
        verify_backup(backup,key_file=settings.data_dir / 'secret.key')


def test_unpacked_budget_and_duplicate_manifest_entries_are_rejected(bundle):
    _,backup = bundle
    with pytest.raises(BackupVerificationError,match='size budget'):
        verify_backup(backup,max_unpacked_bytes=1)
    manifest = backup / 'SHA256SUMS';text=manifest.read_text();manifest.write_text(text+text.splitlines()[0]+'\n')
    with pytest.raises(BackupVerificationError,match='Invalid backup checksum'):
        verify_backup(backup)


def test_multikey_rotation_and_primary_only_backup_recovery(bundle,tmp_path):
    from openreporting.key_rotation import prepare_rotation,prepare_retirement,rekey_secrets
    settings,backup = bundle
    ring = tmp_path / 'rotation-ring.json'
    prepare_rotation(settings,ring)
    rotating = replace(settings,secret_key_file=str(ring))
    assert verify_backup(backup,key_file=ring)['encrypted_sources']==1
    assert rekey_secrets(rotating,services_stopped=True)['sources_rekeyed']==1
    retired = tmp_path / 'primary-only.json'
    prepare_retirement(rotating,retired,services_stopped=True)
    with pytest.raises(BackupVerificationError):
        verify_backup(backup,key_file=retired)
    # The old backup remains recoverable with its old key or the retained ring.
    assert verify_backup(backup,key_file=settings.data_dir / 'secret.key')['ok']
    restored = tmp_path / 'new-backup';restored.mkdir()
    for name in ('archive.tar.gz','openreporting.env'):
        shutil.copyfile(backup / name,restored / name)
    db.backup_database(rotating,restored / 'state.sqlite3')
    checksum(restored)
    assert verify_backup(restored,key_file=retired)['encrypted_sources']==1
    with pytest.raises(BackupVerificationError):
        verify_backup(restored,key_file=settings.data_dir / 'secret.key')
