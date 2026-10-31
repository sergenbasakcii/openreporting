from dataclasses import replace
import json
import os

from cryptography.fernet import Fernet,InvalidToken
import pytest

from openreporting import cli,db,security
from openreporting.config import Settings
from openreporting import key_rotation as rotation
from openreporting.secrets_store import KEYRING_FORMAT,MAX_KEYS,SecretError,decrypt,encrypt,key_id,key_path,read_keys,reset_cache


@pytest.fixture
def state(tmp_path):
    reset_cache()
    settings = replace(Settings.from_env(),data_dir=tmp_path / 'data',database_url='',secret_key_file='',
                       ldap_enabled=False,mail_enabled=False,zabbix_url='',zabbix_token_file='')
    db.init_db(settings)
    security.create_user(settings,'admin1','isolated-rotation-password','admin')
    session = security.login(settings,'admin1','isolated-rotation-password')
    tokens = [encrypt(settings,{'token':f'isolated-source-secret-{i}'}) for i in range(2)]
    with db.connect(settings) as connection,db.transaction(connection):
        for i,token in enumerate(tokens):
            connection.execute('''INSERT INTO datasources
                (id,uid,name,type,secure_json,created_at,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?)''',
                (str(i),'source'+str(i),'Source '+str(i),'testdata',token,'fixture','fixture','fixture'))
        db.audit(connection,'test','fixture.seeded','source','synthetic')
    yield settings,tokens,session
    reset_cache()


def prepared(settings,tmp_path):
    output = tmp_path / 'next-key.json'
    rotation.prepare_rotation(settings,output)
    return replace(settings,secret_key_file=str(output))


def stored(settings):
    with db.connect(settings) as connection:
        return [r[0] for r in connection.execute('SELECT secure_json FROM datasources ORDER BY id')]


def test_preparation_preserves_current_key_database_and_permissions(state,tmp_path):
    settings,tokens,_ = state
    previous = key_path(settings).read_bytes()
    before = settings.db_path.read_bytes()
    next_settings = prepared(settings,tmp_path)
    keys = read_keys(key_path(next_settings))
    assert len(keys)==2 and keys[1]==previous and keys[0]!=previous
    assert key_path(settings).read_bytes()==previous and settings.db_path.read_bytes()==before
    assert decrypt(next_settings,tokens[0])=={'token':'isolated-source-secret-0'}
    fresh = encrypt(next_settings,{'token':'new-primary-secret'})
    with pytest.raises(InvalidToken):
        Fernet(previous).decrypt(fresh.encode())
    if os.name!='nt':
        assert key_path(next_settings).stat().st_mode & 0o777==0o600
    with pytest.raises(SecretError,match='never overwritten'):
        rotation.prepare_rotation(settings,key_path(next_settings))
    assert read_keys(key_path(next_settings))==keys


def test_offline_rekey_retirement_and_account_session_preservation(state,tmp_path):
    settings,tokens,session = state
    next_settings = prepared(settings,tmp_path)
    keys = read_keys(key_path(next_settings))
    primary = Fernet(keys[0]);previous = Fernet(keys[1])
    retired = tmp_path / 'retired.json'
    with pytest.raises(SecretError,match='Offline maintenance'):
        rotation.rekey_secrets(next_settings)
    with pytest.raises(SecretError,match='Old keys still required'):
        rotation.prepare_retirement(next_settings,retired,services_stopped=True)
    assert not retired.exists()
    with db.connect(settings) as connection:
        users = [tuple(r) for r in connection.execute('SELECT * FROM users')]
        sessions = [tuple(r) for r in connection.execute('SELECT * FROM sessions')]
    result = rotation.rekey_secrets(next_settings,services_stopped=True)
    assert result=={'primary_id':key_id(keys[0]),'sources_rekeyed':2,'mfa_secrets_rekeyed':0}
    updated = stored(settings)
    for old,new in zip(tokens,updated):
        assert primary.extract_timestamp(new.encode())==previous.extract_timestamp(old.encode())
        assert primary.decrypt(new.encode())==previous.decrypt(old.encode())
        with pytest.raises(InvalidToken):
            previous.decrypt(new.encode())
    assert rotation.rekey_secrets(next_settings,services_stopped=True)['sources_rekeyed']==0
    rotation.prepare_retirement(next_settings,retired,services_stopped=True)
    final = replace(settings,secret_key_file=str(retired))
    assert read_keys(retired)==[keys[0]] and decrypt(final,updated[0])=={'token':'isolated-source-secret-0'}
    with db.connect(settings) as connection:
        assert users==[tuple(r) for r in connection.execute('SELECT * FROM users')]
        assert sessions==[tuple(r) for r in connection.execute('SELECT * FROM sessions')]
        assert db.verify_audit(connection)==(True,None)
        event = connection.execute("SELECT details FROM audit WHERE action='secrets.rekeyed'").fetchone()[0]
        assert json.loads(event)['sources']==2 and 'secret-' not in event
    assert key_path(settings).read_bytes()==keys[1]
    assert security.login(settings,'admin1','isolated-rotation-password')


def test_bad_second_credential_rolls_back_first_and_audit(state,tmp_path):
    settings,tokens,_ = state
    next_settings = prepared(settings,tmp_path)
    with db.connect(settings) as connection,db.transaction(connection):
        connection.execute("UPDATE datasources SET secure_json='invalid-fixture' WHERE id='1'")
        before = connection.execute('SELECT count(*) FROM audit').fetchone()[0]
    with pytest.raises(SecretError,match='rolled back') as error:
        rotation.rekey_secrets(next_settings,services_stopped=True)
    assert 'invalid-fixture' not in str(error.value)
    assert stored(settings)[0]==tokens[0]
    with db.connect(settings) as connection:
        assert connection.execute('SELECT count(*) FROM audit').fetchone()[0]==before


def test_audit_failure_rolls_back_all_rekey_writes(state,tmp_path,monkeypatch):
    settings,tokens,_ = state
    next_settings = prepared(settings,tmp_path)
    def fail(*args,**kwargs):
        raise OSError('isolated-private-exception')
    monkeypatch.setattr(rotation,'audit',fail)
    with pytest.raises(SecretError,match='rolled back') as error:
        rotation.rekey_secrets(next_settings,services_stopped=True)
    assert stored(settings)==tokens and 'private' not in str(error.value)


@pytest.mark.parametrize('mutation',['version','id','duplicate','extra','too-many','oversize','duplicate-field'])
def test_bad_keyring_fails_without_overwriting_or_leaking_keys(tmp_path,mutation):
    key = Fernet.generate_key();row = {'id':key_id(key),'key':key.decode()}
    data = {'format':KEYRING_FORMAT,'keys':[row]}
    if mutation=='version':data['format']='unknown'
    if mutation=='id':row['id']='incorrect'
    if mutation=='duplicate':data['keys']=[row,row]
    if mutation=='extra':data['ignored']='forbidden'
    if mutation=='too-many':data['keys']=[row]*(MAX_KEYS+1)
    text = json.dumps(data)
    if mutation=='oversize':text += ' '*20000
    if mutation=='duplicate-field':text = '{"format":"x","format":"'+KEYRING_FORMAT+'","keys":[]}'
    target = tmp_path / 'bad-key';target.write_text(text)
    with pytest.raises(SecretError) as error:
        read_keys(target)
    assert key.decode() not in str(error.value) and target.read_text()==text


def test_ring_limit_and_active_output_are_refused(state,tmp_path):
    settings,_,_ = state
    with pytest.raises(SecretError,match='differ'):
        rotation.prepare_rotation(settings,key_path(settings))
    current = settings
    for i in range(MAX_KEYS-1):
        output = tmp_path / f'ring{i}.json'
        rotation.prepare_rotation(current,output)
        current = replace(settings,secret_key_file=str(output))
    with pytest.raises(SecretError,match='limit'):
        rotation.prepare_rotation(current,tmp_path / 'excess.json')
    assert not (tmp_path / 'excess.json').exists()


def test_missing_store_or_experimental_postgres_never_creates_database(state,tmp_path):
    settings,_,_ = state
    next_settings = prepared(settings,tmp_path)
    missing = replace(next_settings,data_dir=tmp_path / 'missing')
    with pytest.raises(SecretError):rotation.rekey_secrets(missing,services_stopped=True)
    assert not missing.db_path.exists()
    with pytest.raises(SecretError,match='SQLite baseline'):
        rotation.rekey_secrets(replace(next_settings,database_url='postgresql://isolated.invalid/database'),services_stopped=True)


def test_cli_preparation_never_initializes_or_migrates_state(state,tmp_path,monkeypatch,capsys):
    settings,_,_ = state
    monkeypatch.setattr(cli.Settings,'from_env',lambda:settings)
    def forbidden(*args):raise AssertionError('init_db must not run')
    monkeypatch.setattr(cli,'init_db',forbidden)
    cli.main(['prepare-key-rotation','--output',str(tmp_path / 'cli-ring.json')])
    output = json.loads(capsys.readouterr().out)
    assert output['key_count']==2 and 'key' not in output


def test_output_symlink_cannot_create_or_overwrite_its_target(state,tmp_path):
    settings,_,_ = state
    target = tmp_path / 'must-not-exist'
    link = tmp_path / 'link'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('Creating symlinks requires Windows privilege')
    with pytest.raises(SecretError):rotation.prepare_rotation(settings,link)
    assert not target.exists()


def test_wrong_schema_is_not_migrated_during_rekey(state,tmp_path):
    settings,tokens,_ = state
    next_settings = prepared(settings,tmp_path)
    with db.connect(settings) as connection:
        connection.execute('PRAGMA user_version=2')
    with pytest.raises(SecretError,match='Matching schema'):
        rotation.rekey_secrets(next_settings,services_stopped=True)
    assert stored(settings)==tokens
    with db.connect(settings) as connection:
        assert db.schema_version(connection)==2
