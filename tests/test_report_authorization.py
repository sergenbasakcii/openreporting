"""Live role/account revocation must apply to queued and scheduled report work."""
from dataclasses import replace
from datetime import datetime,timezone

from fastapi.testclient import TestClient
import pytest

from openreporting import dashboards,db,security
from openreporting.config import Settings
from openreporting.reporting import service
from openreporting.web import create_app


@pytest.fixture
def state(tmp_path):
    settings=replace(Settings.from_env(),data_dir=tmp_path,database_url='',secret_key_file='',secure_cookie=False,
                     ldap_enabled=False,mail_enabled=False,mfa_required_roles=(),zabbix_url='',zabbix_token_file='',
                     recipient_domains=('example.com',))
    app=create_app(settings)
    admin={'id':security.create_user(settings,'owner','isolated-owner-password','admin'),'role':'admin'}
    editor={'id':security.create_user(settings,'editor','isolated-editor-password','editor'),'role':'editor'}
    dashboards.save(settings,admin,{'uid':'entitlement','title':'Entitlement fixture','panels':[
        {'id':1,'type':'timeseries','targets':[{'refId':'A','scenario':'sine','datasource':{'uid':'testdata'}}]}]})
    report=service.save_report(settings,admin,{'name':'Entitlement report','dashboard_uid':'entitlement','formats':['csv']})
    return settings,app,admin,editor,report['id']


def revoke(settings,actor,change):
    with db.connect(settings) as conn,db.transaction(conn):
        if change=='disabled':conn.execute('UPDATE users SET active=0 WHERE id=?',(actor['id'],))
        elif change=='viewer':conn.execute("UPDATE users SET role='viewer' WHERE id=?",(actor['id'],))
        elif change=='editor':conn.execute("UPDATE users SET role='editor' WHERE id=?",(actor['id'],))
        elif change=='ldap_disabled':
            conn.execute("INSERT INTO external_identities(user_id,provider,subject) VALUES(?,'ldap','synthetic-revocation-id')",(actor['id'],))


@pytest.mark.parametrize('change',['disabled','viewer','ldap_disabled'])
def test_manual_queued_run_blocks_before_query_when_actor_loses_entitlement(state,monkeypatch,change):
    settings,_,admin,_,rid=state
    run=service.request_run(settings,admin,rid,{})['run_id']
    revoke(settings,admin,change)
    monkeypatch.setattr(service,'build_outputs',lambda *a,**k:pytest.fail('Revoked actor must not query/render'))
    service.execute(settings,run)
    result=service.list_runs(settings,rid)[0]
    assert result['status']=='blocked' and result['delivery_status']=='blocked_revalidation'
    assert result['files']=={} and list(settings.archive_dir.iterdir())==[]
    with db.connect(settings) as conn:
        assert db.verify_audit(conn)==(True,None)
        assert conn.execute("SELECT count(*) FROM audit WHERE action='report_run.blocked_authorization'").fetchone()[0]==1


def due_schedule(settings,admin,rid):
    schedule=service.save_schedule(settings,admin,rid,{'cadence':'hourly','enabled':True})
    with db.connect(settings) as conn,db.transaction(conn):
        conn.execute('UPDATE dash_report_schedules SET next_due=? WHERE id=?',
                     (datetime.now(timezone.utc).replace(microsecond=0).isoformat(),schedule['id']))
    return schedule['id']


@pytest.mark.parametrize('change',['disabled','editor','ldap_disabled','unapproved'])
def test_scheduler_disables_revoked_or_missing_approval_and_does_not_enqueue(state,change):
    settings,_,admin,_,rid=state
    sid=due_schedule(settings,admin,rid)
    if change=='unapproved':
        with db.connect(settings) as conn,db.transaction(conn):
            conn.execute('UPDATE dash_report_schedules SET approved_by=NULL WHERE id=?',(sid,))
    else:revoke(settings,admin,change)
    service.tick_schedules(settings);service.tick_schedules(settings)
    assert service.list_runs(settings,rid)==[]
    assert service.list_schedules(settings,rid)[0]['enabled']==0
    with db.connect(settings) as conn:
        assert conn.execute("SELECT count(*) FROM audit WHERE action='report_schedule.disabled_authorization'").fetchone()[0]==1


def test_schedule_revocation_after_enqueue_blocks_worker(state,monkeypatch):
    settings,_,admin,_,rid=state
    due_schedule(settings,admin,rid);service.tick_schedules(settings)
    run=service.list_runs(settings,rid)[0]
    assert run['created_by'] is None  # Worker must check approver, never an implicit system admin.
    revoke(settings,admin,'editor')
    monkeypatch.setattr(service,'build_outputs',lambda *a,**k:pytest.fail('Revoked approval must not render'))
    service.execute(settings,run['id'])
    assert service.list_runs(settings,rid)[0]['status']=='blocked'


def test_revocation_during_render_discards_outputs_before_archive(state,monkeypatch):
    settings,_,admin,_,rid=state
    run=service.request_run(settings,admin,rid,{})['run_id']
    original=service.build_outputs
    def render(*args,**kwargs):
        result=original(*args,**kwargs)
        revoke(settings,admin,'disabled')
        return result
    monkeypatch.setattr(service,'build_outputs',render)
    service.execute(settings,run)
    assert service.list_runs(settings,rid)[0]['status']=='blocked'
    assert list(settings.archive_dir.iterdir())==[]


def test_role_loss_after_archive_blocks_smtp_before_side_effect(state,monkeypatch):
    settings,_,admin,_,rid=state
    settings=replace(settings,mail_enabled=True,smtp_host='smtp.example.com',smtp_from='reports@example.com')
    run=service.request_run(settings,admin,rid,{'recipients':['reader@example.com']})['run_id']
    original=service._atomic_write
    def write(path,data):
        original(path,data)
        if path.suffix=='.json':revoke(settings,admin,'editor')
    monkeypatch.setattr(service,'_atomic_write',write)
    monkeypatch.setattr(service,'send_mail',lambda *a,**k:pytest.fail('Revoked sender must not reach SMTP'))
    service.execute(settings,run)
    result=service.list_runs(settings,rid)[0]
    assert result['status']=='completed' and result['delivery_status']=='blocked_revalidation'


def test_archive_only_editor_run_remains_allowed_but_stale_admin_mail_request_does_not(state):
    settings,_,admin,editor,rid=state
    run=service.request_run(settings,editor,rid,{})['run_id']
    service.execute(settings,run)
    assert service.list_runs(settings,rid)[0]['status']=='completed'
    revoke(settings,admin,'editor')
    # An editor still has archive-only entitlement; the change must not over-block it.
    archive_run=service.request_run(settings,admin,rid,{})['run_id']
    service.execute(settings,archive_run)
    assert next(r for r in service.list_runs(settings,rid) if r['id']==archive_run)['status']=='completed'
    settings=replace(settings,mail_enabled=True,smtp_host='smtp.example.com',smtp_from='reports@example.com')
    with pytest.raises(service.ReportError,match='yetkisi'):
        service.request_run(settings,admin,rid,{'recipients':['reader@example.com']})
    with pytest.raises(service.ReportError,match='yetkisi'):
        service.save_schedule(settings,admin,rid,{'cadence':'hourly','enabled':True})


def test_api_user_deactivation_revokes_session_and_blocks_queued_work(state,monkeypatch):
    settings,app,_,editor,rid=state
    with TestClient(app,base_url='http://localhost') as operator,TestClient(app,base_url='http://localhost') as owner:
        signed=owner.post('/api/login',json={'username':'editor','password':'isolated-editor-password'})
        queued=owner.post(f'/api/dash-reports/{rid}/runs',json={},headers={'X-CSRF-Token':signed.json()['csrf']})
        assert queued.status_code==200
        signed=operator.post('/api/login',json={'username':'owner','password':'isolated-owner-password'})
        revoked=operator.patch(f'/api/users/{editor["id"]}',json={'active':False},headers={'X-CSRF-Token':signed.json()['csrf']})
        assert revoked.status_code==200 and owner.get('/api/user').status_code==401
        monkeypatch.setattr(service,'build_outputs',lambda *a,**k:pytest.fail('Revoked API account must not render'))
        service.execute(settings,queued.json()['run_id'])
        assert service.list_runs(settings,rid)[0]['status']=='blocked'
