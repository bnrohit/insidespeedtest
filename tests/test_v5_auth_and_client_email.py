"""v5 integration regression: login/logout isolation, CSRF and bounded email requests."""
import hashlib
import sqlite3

from fastapi.testclient import TestClient
from app.main import Settings, create_app
from app.client_email import update_client_email


def fixture_app(tmp_path, **kwargs):
    mapping = tmp_path / 'networks.csv'
    mapping.write_text('scope,school,vlan,cidr,label\nschool,GPHS,,10.44.0.0/20,School\nvlan,GPHS,48,10.44.1.0/24,Staff\n')
    settings = Settings(db_path=str(tmp_path / 'results.db'), mapping_path=str(mapping),
                        admin_username='gmcsadmin', admin_password='TEST_PASSWORD_32_CHARS_MINIMUM_12345',
                        admin_client_cidrs='10.0.0.0/8',
                        **kwargs)
    return create_app(settings), settings


def browser(app, ip='10.44.1.50'):
    return TestClient(app, base_url='https://speedtest.test', client=(ip, 40000))


def login(c):
    response = c.post('/api/admin/login', json={'username':'gmcsadmin', 'password':'TEST_PASSWORD_32_CHARS_MINIMUM_12345'})
    assert response.status_code == 204, response.text
    assert 'httponly' in response.headers['set-cookie'].lower()
    assert 'secure' in response.headers['set-cookie'].lower()
    assert 'samesite=strict' in response.headers['set-cookie'].lower()
    return c.get('/api/admin/session').json()['csrf_token']


def test_admin_sessions_are_independent_and_logout_requires_csrf(tmp_path):
    app, settings = fixture_app(tmp_path)
    a, b = browser(app), browser(app)
    assert 'Sign' in a.get('/admin').text
    assert a.get('/api/admin/summary').status_code == 401
    assert a.get('/admin', auth=('gmcsadmin', settings.admin_password)).status_code == 200
    assert a.get('/api/admin/summary', auth=('gmcsadmin', settings.admin_password)).status_code == 401
    csrf_a = login(a)
    csrf_b = login(b)
    assert a.get('/api/admin/summary').status_code == 200
    assert b.get('/api/admin/summary').status_code == 200
    assert a.post('/api/admin/logout').status_code == 403
    assert a.post('/api/admin/logout', headers={'X-CSRF-Token':'wrong'}).status_code == 403
    assert a.post('/api/admin/logout', headers={'X-CSRF-Token':csrf_a}).status_code == 204
    assert a.get('/api/admin/summary').status_code == 401
    assert b.get('/api/admin/summary').status_code == 200
    assert b.post('/api/admin/logout', headers={'X-CSRF-Token':csrf_b}).status_code == 204
    assert b.get('/api/admin/summary').status_code == 401


def test_admin_mutations_need_same_origin_and_csrf(tmp_path):
    app, _ = fixture_app(tmp_path)
    c = browser(app)
    csrf = login(c)
    path = '/api/admin/config/smtp'
    data = {'host':'127.0.0.1','port':25,'tls_mode':'none','sender':'alerts@example.test','recipients':'noc@example.test'}
    assert c.put(path, json=data).status_code == 403
    assert c.put(path, json=data, headers={'X-CSRF-Token':csrf, 'Origin':'https://malicious.test','Sec-Fetch-Site':'cross-site'}).status_code == 403
    r = c.put(path, json=data, headers={'X-CSRF-Token':csrf,'Origin':'https://speedtest.test','Sec-Fetch-Site':'same-origin'})
    assert r.status_code == 200, r.text


def make_result(client):
    resp = client.post('/api/session')
    assert resp.status_code == 200, resp.text
    token = resp.json()['token']
    headers = {'X-Speedtest-Token':token}
    assert client.get('/api/download?bytes=1024', headers=headers).status_code == 200
    assert client.post('/api/upload', content=b'1234', headers=headers).status_code == 200
    result = client.post('/api/results', json={'token':token,'download_mbps':30,'upload_mbps':20,
                          'latency_ms':1,'jitter_ms':1,'packet_loss_pct':0,
                          'download_bytes':1024,'upload_bytes':4})
    assert result.status_code == 200, result.text
    return result.json(), token


def test_client_email_only_own_completed_result_and_no_duplicates(tmp_path, monkeypatch):
    import app.main as main
    app, settings = fixture_app(tmp_path, smtp_host='relay.example.test',
                                smtp_from='inside@example.test',
                                smtp_to=('gmcsadmin@example.test',), email_browser_results=False)
    delivered = []
    def send(settings, result_id, row):
        delivered.append(result_id)
        update_client_email(settings.db_path, result_id, 'sent')
    monkeypatch.setattr(main, 'send_client_result', send)
    c, other = browser(app), browser(app,'10.44.1.51')
    response, token = make_result(c)
    rid = response['result_id']
    assert response['client_email_available'] is True
    assert c.post(f'/api/results/{rid}/email',json={'token':'incorrect-token-not-good-123456789012345'}).status_code == 403
    assert other.post(f'/api/results/{rid}/email',json={'token':token}).status_code == 403
    r = c.post(f'/api/results/{rid}/email',json={'token':token})
    assert r.status_code == 200, r.text
    assert delivered == [rid]
    assert c.post(f'/api/results/{rid}/email',json={'token':token}).status_code == 409
    with sqlite3.connect(settings.db_path) as db:
        assert db.execute('SELECT client_email_status FROM results WHERE id=?',(rid,)).fetchone()[0]=='sent'


def test_admin_password_change_invalidates_prior_session(tmp_path):
    app, settings = fixture_app(tmp_path)
    c = browser(app)
    login(c)
    assert c.get('/api/admin/results').status_code == 200
    changed = Settings(**{**settings.__dict__, 'admin_password':'ROTATED_NEW_PASSWORD_987654321000'})
    recreated = browser(create_app(changed))
    for cookie in c.cookies.jar:
        recreated.cookies.set(cookie.name, cookie.value, domain='speedtest.test', path=cookie.path)
    assert recreated.get('/api/admin/results').status_code == 401
