import os
os.environ.setdefault('ADMIN_PASSWORD','TEST_ONLY_A_LONG_RANDOM_ADMIN_PASSWORD')
from fastapi.testclient import TestClient
from app.main import create_app, Settings


def setup_client(tmp_path, **kwargs):
    config = tmp_path/'network.csv'
    config.write_text('scope,school,vlan,cidr,label\nschool,GPHS,,10.44.0.0/20,GPHS campus\nvlan,GPHS,48,10.44.1.0/24,Staff\n')
    settings = Settings(db_path=str(tmp_path/'test.db'),mapping_path=str(config),admin_username='admin',admin_password='test_password_1234567890',cooldown_seconds=30,
                        admin_client_cidrs='10.0.0.0/8,127.0.0.0/8',allow_legacy_basic_api=True,**kwargs)
    return TestClient(create_app(settings),base_url='https://testserver',client=('10.44.1.50',31337))


def test_full_test_flow_and_auth(tmp_path):
    client = setup_client(tmp_path)
    assert client.get('/healthz').json()=={'status':'ok'}
    identity = client.get('/api/identity').json()
    assert identity['school']=='GPHS' and identity['vlan']=='48' and identity['client_ip']=='10.44.1.50'
    assert client.get('/admin').status_code==200  # v5 serves a login form to unauthenticated users
    assert client.get('/api/admin/results').status_code==401
    assert client.get('/admin',auth=('admin','test_password_1234567890')).status_code==200
    assert client.get('/api/download?bytes=1024').status_code==401
    token = client.post('/api/session').json()['token']
    headers={'X-Speedtest-Token':token}
    assert len(client.get('/api/download?bytes=1024',headers=headers).content)==1024
    assert client.post('/api/upload', content=b'abcd',headers=headers).json()['bytes_received']==4
    assert client.get('/api/ping',headers=headers).status_code==204
    result = {'token':token,'download_mbps':450.5,'upload_mbps':225.8,'latency_ms':12.3,'jitter_ms':2.4,'packet_loss_pct':0,'download_bytes':1024,'upload_bytes':4}
    response=client.post('/api/results',json=result)
    assert response.status_code==200
    assert response.json()['school']=='GPHS'
    assert client.post('/api/results',json=result).status_code==400
    assert client.get('/api/download?bytes=1024',headers=headers).status_code==401
    records=client.get('/api/admin/results',auth=('admin','test_password_1234567890')).json()['results']
    assert len(records)==1 and records[0]['email_status']=='disabled'
    assert 'GPHS' in client.get('/api/admin/export.csv',auth=('admin','test_password_1234567890')).text


def test_reject_untrusted_proxy_header(tmp_path):
    client=setup_client(tmp_path)
    result=client.get('/api/identity',headers={'X-Real-IP':'10.44.9.1','X-Forwarded-For':'10.44.9.1'})
    assert result.json()['client_ip']=='10.44.1.50'


def test_proxy_only_from_allowlist(tmp_path):
    client=setup_client(tmp_path,trusted_proxy_cidrs='10.44.1.50/32')
    response=client.get('/api/identity',headers={'X-Real-IP':'10.44.3.24'})
    assert response.json()['client_ip']=='10.44.3.24'
    assert response.json()['school']=='GPHS' and response.json()['vlan']=='Unknown'


def test_limited_source_and_invalid_payload(tmp_path):
    client=setup_client(tmp_path,allowed_client_cidrs='192.0.2.0/24')
    assert client.get('/api/identity').status_code==403
    assert client.post('/api/session').status_code==403


def test_browser_tests_from_same_vlan_email_only_once(tmp_path, monkeypatch):
    """No browser login; two sources in one VLAN => two records, one email."""
    import app.main as main_module
    from app.database import set_email_status
    from fastapi.testclient import TestClient

    client = setup_client(tmp_path, smtp_host='relay.example.invalid',
                          smtp_from='speedtest@example.invalid',
                          smtp_to=('admin@example.invalid',))
    delivered = []

    def fake_email(settings, result_id, record):
        delivered.append((record['school'], record['vlan'], result_id))
        set_email_status(settings.db_path, result_id, 'sent')

    monkeypatch.setattr(main_module, 'send_result', fake_email)

    def complete(source):
        with TestClient(client.app, base_url='https://testserver', client=(source, 31337)) as c:
            response = c.post('/api/session')
            assert response.status_code == 200, response.text
            token = response.json()['token']
            headers = {'X-Speedtest-Token': token}
            assert c.get('/api/download?bytes=1024', headers=headers).status_code == 200
            assert c.post('/api/upload', content=b'1234', headers=headers).status_code == 200
            payload = dict(token=token, download_mbps=42, upload_mbps=25,
                           latency_ms=8, jitter_ms=1, packet_loss_pct=0,
                           download_bytes=1024, upload_bytes=4)
            resp = c.post('/api/results', json=payload)
            assert resp.status_code == 200, resp.text
            return resp.json()

    first = complete('10.44.1.50')
    second = complete('10.44.1.51')
    assert first['school'] == 'GPHS' and first['vlan'] == '48'
    assert first['email_notification'] == 'queued'
    assert second['email_notification'] == 'suppressed'
    assert len(delivered) == 1 and delivered[0][:2] == ('GPHS', '48')
    statuses = [r['email_status'] for r in client.get('/api/admin/results',
                 auth=('admin', 'test_password_1234567890')).json()['results']]
    assert sorted(statuses) == ['sent', 'suppressed']


def test_scheduled_agent_requires_valid_key_from_source_ip(tmp_path):
    import hashlib
    token = 'SECURE_TEST_AGENT_KEY_NOT_FOR_PRODUCTION_00000001'
    config = tmp_path / 'agents.csv'
    config.write_text('agent_id,token_sha256,allowed_cidr\nCACHE01,' +
                      hashlib.sha256(token.encode()).hexdigest() + ',10.44.1.50/32\n')
    client = setup_client(tmp_path, agents_path=str(config))
    assert client.post('/api/session', headers={'X-Agent-Id': 'CACHE01',
        'X-Agent-Key': 'wrong-password-not-allowed'}).status_code == 401
    response = client.post('/api/session', headers={'X-Agent-Id': 'CACHE01',
        'X-Agent-Key': token})
    assert response.status_code == 200
    assert response.json()['agent_id'] == 'CACHE01'
