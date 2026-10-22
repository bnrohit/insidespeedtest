"""Safe diagnostic capture and admin-only access regression tests."""
import sqlite3
from fastapi.testclient import TestClient
from app.main import Settings, create_app
from app.diagnostics import assess, validate_advanced


def setup(tmp_path):
    mapfile = tmp_path/'networks.csv'
    mapfile.write_text('scope,school,vlan,cidr,label\nschool,LNE,,10.64.0.0/16,School\n')
    settings = Settings(db_path=str(tmp_path/'results.sqlite3'),mapping_path=str(mapfile),
                        admin_username='gmcsadmin',admin_password='TEST_PASSWORD_LONG_SECURE_456789',
                        admin_client_cidrs='10.0.0.0/8')
    return create_app(settings), settings


def finished(c,diag=None):
    response = c.post('/api/session')
    assert response.status_code == 200, response.text
    token = response.json()['token']
    h = {'x-speedtest-token':token}
    assert c.get('/api/download?bytes=1024',headers=h).status_code == 200
    assert c.post('/api/upload', content=b'abc',headers=h).status_code == 200
    body = {'token':token,'download_mbps':2.2,'upload_mbps':18.2,'latency_ms':85,
            'jitter_ms':45,'packet_loss_pct':20,'download_bytes':1024,'upload_bytes':3}
    if diag is not None:body['browser_diagnostics']=diag
    r=c.post('/api/results',json=body)
    assert r.status_code==200,r.text
    return r.json()['result_id'],token


def test_browser_diagnostics_and_admin_triage(tmp_path):
    app,settings=setup(tmp_path)
    c=TestClient(app,base_url='https://gmcs.test',client=('10.64.241.13',49152))
    rid,token=finished(c,{'platform':'Windows','browser':'Edge','network_type':'4g',
                            'online':True,'https_rtt_ms':7.5})
    assert c.get(f'/api/admin/results/{rid}/diagnostics').status_code==401
    assert c.post('/api/admin/login',json={'username':'gmcsadmin',
                            'password':settings.admin_password}).status_code==204
    r=c.get(f'/api/admin/results/{rid}/diagnostics')
    assert r.status_code==200,r.text
    report=r.json()
    assert report['browser']['platform']=='Windows'
    assert report['advanced'] is None
    assert any(x['severity']=='high' for x in report['assessment'])
    assert all(x['next_step'] for x in report['assessment'])
    assert 'token_hash' not in report


def test_advanced_report_consent_ip_and_token(tmp_path):
    app,settings=setup(tmp_path)
    a=TestClient(app,base_url='https://gmcs.test',client=('10.64.241.15',49152))
    other=TestClient(app,base_url='https://gmcs.test',client=('10.64.241.13',49153))
    rid,token=finished(a)
    doc={'token':token,'platform':'Windows','hostname':'CLIENT-A',
         'commands':{'ipconfig':'DNS: 10.100.17.11','ping_internal':'Request timed out',
                     'nslookup_google':'Server: dns.google'}}
    assert other.post(f'/api/results/{rid}/diagnostics/advanced',json=doc).status_code==403
    assert a.post(f'/api/results/{rid}/diagnostics/advanced',json={**doc,'token':'a'*43}).status_code==403
    assert a.post(f'/api/results/{rid}/diagnostics/advanced',json={**doc,'commands':{'arbitrary_shell_command':'pwd'}}).status_code==422
    assert a.post(f'/api/results/{rid}/diagnostics/advanced',json={**doc,'commands':{'arp':'x'*4000}}).status_code==422
    saved=a.post(f'/api/results/{rid}/diagnostics/advanced',json=doc)
    assert saved.status_code==200,saved.text
    assert a.post(f'/api/results/{rid}/diagnostics/advanced',json=doc).status_code==403
    assert a.post('/api/admin/login',json={'username':'gmcsadmin','password':settings.admin_password}).status_code==204
    content=a.get(f'/api/admin/results/{rid}/diagnostics').json()
    assert content['advanced']['hostname']=='CLIENT-A'
    assert any(x['area']=='Internal DNS-server reachability' for x in content['assessment'])
    with sqlite3.connect(settings.db_path) as sql:
        assert sql.execute('SELECT COUNT(*) FROM client_diagnostics').fetchone()[0]==1


def test_advanced_submissions_require_https_even_with_correct_token(tmp_path):
    app,_=setup(tmp_path)
    c=TestClient(app,base_url='http://gmcs.test',client=('10.64.241.15',49152))
    rid,token=finished(c)
    response=c.post(f'/api/results/{rid}/diagnostics/advanced',json={
      'token':token,'platform':'macOS','hostname':'mac','commands':{'ifconfig':'no info'}})
    assert response.status_code==403


def test_reports_are_suggestions_not_diagnosis():
    report={'packet_loss_pct':0,'jitter_ms':1,'latency_ms':2,'download_mbps':30,
            'upload_mbps':30,'advanced':None}
    assert assess(report)[0]['area']=='No decisive fault signature'
    for bad in [{}, {'platform':'Windows','hostname':'a','commands':{}},
                {'platform':'Linux','hostname':'a','commands':{'arp':'x'}},
                {'platform':'Windows','hostname':'a','commands':{'secrets':'x'}}]:
        try:validate_advanced(bad)
        except ValueError:pass
        else:raise AssertionError('Dangerous diagnostics accepted')
