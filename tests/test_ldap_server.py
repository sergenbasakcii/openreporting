"""Actual OpenLDAP TLS/bind/search/memberOf contract on an isolated local server.

CI sets OPENREPORTING_TEST_SLAPD=1 and installs slapd. Other environments skip it.
No existing directory is contacted or changed.
"""
import json
import os
import shutil
import socket
import ssl
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from openreporting.config import Settings
from openreporting import directory_auth
from tests.tls_fixture import certificates


@pytest.fixture
def directory(tmp_path):
    if os.getenv('OPENREPORTING_TEST_SLAPD') != '1':
        pytest.skip('Isolated OpenLDAP server runs in LDAP integration CI')
    executable = shutil.which('slapd') or '/usr/sbin/slapd'
    assert os.path.isfile(executable), 'LDAP CI requires slapd; do not silently skip a missing server'
    import ldap3
    ca, cert, key = certificates(tmp_path)
    # Ubuntu confines slapd to its standard config/data roots. Keep that policy
    # enabled and provision only unique test-owned directories inside those roots.
    database = Path(os.environ.get('OPENREPORTING_TEST_LDAP_DATA_ROOT', str(tmp_path))) / tmp_path.name
    database.mkdir()
    def free_port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]
    port, ssl_port = free_port(), free_port()
    config = tmp_path / 'slapd.conf'
    config.write_text(f'''
include /etc/ldap/schema/core.schema
include /etc/ldap/schema/cosine.schema
include /etc/ldap/schema/inetorgperson.schema
modulepath /usr/lib/ldap
moduleload back_mdb
moduleload memberof
TLSCertificateFile {cert}
TLSCertificateKeyFile {key}
TLSCACertificateFile {ca}
TLSProtocolMin 3.3
database mdb
maxsize 1073741824
suffix "dc=example,dc=com"
rootdn "cn=root,dc=example,dc=com"
rootpw isolated-root-password
directory {database}
index objectClass eq
access to attrs=userPassword by anonymous auth by * none
access to * by dn.exact="cn=bind,dc=example,dc=com" read by * none
overlay memberof
memberof-group-oc groupOfNames
memberof-member-ad member
memberof-memberof-ad memberOf
''', encoding='utf8')
    checked = subprocess.run([executable, '-Tt', '-u', '-f', str(config)], capture_output=True, text=True, timeout=10)
    assert checked.returncode == 0, 'Isolated directory config invalid: ' + checked.stderr[-2000:]
    with (tmp_path / 'slapd.log').open('w') as log:
        process = subprocess.Popen([executable, '-f', str(config), '-h', f'ldap://127.0.0.1:{port} ldaps://127.0.0.1:{ssl_port}', '-d', '256'], stdout=log, stderr=log)
        root = None
        try:
            tls = ldap3.Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=str(ca))
            for _ in range(80):
                if process.poll() is not None:
                    pytest.fail('Isolated slapd exited: ' + (tmp_path / 'slapd.log').read_text()[-1500:])
                try:
                    root = ldap3.Connection(ldap3.Server('localhost', port=ssl_port, use_ssl=True, tls=tls, get_info=ldap3.NONE, connect_timeout=1),
                                             user='cn=root,dc=example,dc=com', password='isolated-root-password', auto_bind=True)
                    break
                except Exception:
                    time.sleep(.1)
            assert root and root.bound, 'Isolated slapd did not become ready'
            nodes = [
                ('dc=example,dc=com', ['top','domain'], {'dc':'example'}),
                ('cn=bind,dc=example,dc=com', ['organizationalRole','simpleSecurityObject'], {'cn':'bind','userPassword':'isolated-service-password'}),
                ('uid=reader,dc=example,dc=com', ['inetOrgPerson'], {'uid':'reader','cn':'Reader','sn':'Reader','displayName':'Directory Reader','mail':'reader@example.com','userPassword':'isolated-user-password'}),
                ('cn=readers,dc=example,dc=com', ['groupOfNames'], {'cn':'readers','member':'uid=reader,dc=example,dc=com'}),
            ]
            for dn, classes, attributes in nodes:
                assert root.add(dn, classes, attributes), root.result
            settings = replace(Settings.from_env(), data_dir=tmp_path / 'app', secret_key_file='', database_url='', ldap_enabled=True,
                               ldap_url=f'ldaps://localhost:{ssl_port}', ldap_bind_dn='cn=bind,dc=example,dc=com', ldap_bind_password='isolated-service-password',
                               ldap_base_dn='dc=example,dc=com', ldap_user_filter='(&(objectClass=inetOrgPerson)(uid={username}))', ldap_id_attribute='entryUUID',
                               ldap_group_roles=json.dumps({'cn=readers,dc=example,dc=com':'viewer','cn=editors,dc=example,dc=com':'editor'}), ldap_ca_file=str(ca), ldap_timeout=3)
            yield settings, root, port
        finally:
            if root:
                root.unbind()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize('mode', ['ldaps','starttls'])
def test_actual_directory_admission_role_changes_and_tls(directory, mode):
    import ldap3
    settings, root, port = directory
    if mode == 'starttls':
        settings = replace(settings, ldap_url=f'ldap://localhost:{port}')
    directory_auth.validate_settings(settings)
    assert directory_auth.check_connection(settings)
    first = directory_auth.authenticate(settings, 'reader', 'isolated-user-password')
    assert first and first.role == 'viewer' and first.email == 'reader@example.com' and first.subject
    assert directory_auth.authenticate(settings, 'reader', 'wrong-password') is None
    assert directory_auth.authenticate(settings, 'reader*)(uid=*)', 'isolated-user-password') is None
    assert directory_auth.authenticate(settings, 'reader', '') is None
    assert root.add('cn=editors,dc=example,dc=com', ['groupOfNames'], {'cn':'editors','member':'uid=reader,dc=example,dc=com'}), root.result
    second = directory_auth.authenticate(settings, 'reader', 'isolated-user-password')
    assert second.role == 'editor' and second.subject == first.subject
    assert root.modify('cn=editors,dc=example,dc=com', {'member':[(ldap3.MODIFY_REPLACE,['cn=bind,dc=example,dc=com'])]}), root.result
    assert directory_auth.authenticate(settings, 'reader', 'isolated-user-password').role == 'viewer'
    assert root.modify('cn=readers,dc=example,dc=com', {'member':[(ldap3.MODIFY_REPLACE,['cn=bind,dc=example,dc=com'])]}), root.result
    assert directory_auth.authenticate(settings, 'reader', 'isolated-user-password') is None
    # Our application service account truly has no directory write permission.
    with directory_auth._connection(settings, settings.ldap_bind_dn, settings.ldap_bind_password) as service:
        assert service.bind() and service.read_only
        from ldap3.core.exceptions import LDAPConnectionIsReadOnlyError
        with pytest.raises(LDAPConnectionIsReadOnlyError):
            service.add('cn=forbidden,dc=example,dc=com', ['organizationalRole'], {'cn':'forbidden'})
    for override in ({'ldap_ca_file':''}, {'ldap_url':settings.ldap_url.replace('localhost','127.0.0.1')}):
        with pytest.raises(directory_auth.DirectoryUnavailable):
            directory_auth.check_connection(replace(settings, **override))
    with pytest.raises(directory_auth.DirectoryUnavailable):
        directory_auth.check_connection(replace(settings, ldap_bind_password='wrong-service-password'))
