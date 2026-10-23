"""Admin configuration must not leak secrets or allow public users to mutate settings."""
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app
from app.management import validate_mapping_csv


@pytest.fixture
def client(tmp_path):
    mapping=tmp_path / 'incoming-networks.csv'
    mapping.write_text('scope,school,vlan,cidr,label\nschool,LNE,,10.12.0.0/16,Campus\nvlan,LNE,48,10.12.48.0/21,Staff\n')
    agents=tmp_path / 'incoming-agents.csv'
    agents.write_text('agent_id,token_sha256,allowed_cidr\n')
    settings=Settings(db_path=str(tmp_path/'data'/'results.db'),mapping_path=str(mapping),
                      agents_path=str(agents),admin_username='admin',admin_password='TESTPASSWORD_LONG_123456',
                      admin_client_cidrs='10.12.0.0/16', allow_legacy_basic_api=True)
    app=create_app(settings)
    return TestClient(app,base_url='https://testserver',client=('10.12.48.50',4444)),settings


def test_admin_only_and_persistent_smtp(client):
    c,settings=client
    path='/api/admin/config/smtp'
    assert c.get(path).status_code==401
    assert c.put(path,json={'host':'mail.test.local'}).status_code==401
    admin=('admin','TESTPASSWORD_LONG_123456')
    response=c.put(path,auth=admin,json={'host':'127.0.0.1','port':25,'tls_mode':'starttls',
                           'username':'','sender':'speedtest@example.org','recipients':'noc@example.org',
                           'password':'SOME-LOCAL-SECRET','dedupe_seconds':86400,
                           'email_agent_results':True,'email_browser_results':True})
    assert response.status_code==200,response.text
    assert 'SOME-LOCAL-SECRET' not in response.text
    assert response.json()['password_configured']
    assert c.get(path,auth=admin).json()['host']=='127.0.0.1'
    cfgfile=Path(settings.db_path).parent/'managed'/'smtp.json'
    assert cfgfile.exists() and cfgfile.stat().st_mode & 0o077==0
    after_restart=TestClient(create_app(settings),base_url='https://testserver',client=('10.12.48.50',4444))
    assert after_restart.get(path,auth=admin).json()['host']=='127.0.0.1'
    assert after_restart.get(path,auth=admin).json()['password_configured'] is True
    assert c.put(path,auth=admin,json={'host':'127.0.0.1','port':25,'tls_mode':'none','username':'login'}).status_code==422
    assert c.post('/api/admin/config/smtp/test',auth=admin).status_code in {502,429}
    assert c.post('/api/admin/config/smtp/test').status_code==401


def test_mapping_update_protected_validated_and_survives_restart(client):
    c,settings=client
    admin=('admin','TESTPASSWORD_LONG_123456')
    url='/api/admin/config/networks'
    before=c.get('/api/identity').json()
    assert before['vlan']=='48'
    invalid='scope,school,vlan,cidr,label\nvlan,LNE,48,10.12.0.0/16,Staff\nvlan,TGH,18,10.12.18.0/24,Phones\n'
    assert c.put(url,json={'csv_text':invalid},auth=admin).status_code==422
    assert c.get('/api/identity').json()['vlan']=='48'
    valid='scope,school,vlan,cidr,label\nschool,LNE,,10.12.0.0/16,Campus\nvlan,LNE,56,10.12.48.0/21,Secondary\n'
    assert c.put(url,json={'csv_text':valid}).status_code==401
    assert c.put(url,json={'csv_text':valid},auth=admin).status_code==200
    assert c.get('/api/identity').json()['vlan']=='56'
    c2=TestClient(create_app(settings),base_url='https://testserver',client=('10.12.48.50',4444))
    assert c2.get('/api/identity').json()['vlan']=='56'
    assert c2.get('/api/admin/config/networks.csv',auth=admin).text==valid
    assert c.get('/api/admin/config/networks.csv').status_code==401


def test_agent_ui_generation_one_time_credential_and_revoke(client):
    c,settings=client
    admin=('admin','TESTPASSWORD_LONG_123456')
    url='/api/admin/config/agents'
    assert c.post(url,json={'agent_id':'LNE-CACHE01','allowed_cidr':'10.12.48.50/32'}).status_code==401
    assert c.post(url,auth=admin,json={'agent_id':'LNE-CACHE01','allowed_cidr':'10.12.0.0/16'}).status_code==422
    response=c.post(url,auth=admin,json={'agent_id':'LNE-CACHE01','allowed_cidr':'10.12.48.50/32'})
    assert response.status_code==200,response.text
    key=response.json()['one_time_token']
    assert len(key)>48
    assert key not in c.get(url,auth=admin).text
    saved=Path(settings.db_path).parent/'managed'/'agents.csv'
    assert key not in saved.read_text()
    assert hashlib.sha256(key.encode()).hexdigest() in saved.read_text()
    hdr={'X-Agent-Id':'LNE-CACHE01','X-Agent-Key':key}
    assert c.post('/api/session',headers=hdr).status_code==200
    assert c.delete(url+'/LNE-CACHE01',auth=admin).status_code==200
    assert c.post('/api/session',headers=hdr).status_code==401
    assert c.get(url).status_code==401


def test_reject_public_ranges_and_conflicting_vlan_inventories():
    with pytest.raises(ValueError):
        validate_mapping_csv('scope,school,vlan,cidr,label\nvlan,S,48,8.8.8.0/24,Public\n')
    with pytest.raises(ValueError):
        validate_mapping_csv('scope,school,vlan,cidr,label\nvlan,S,48,10.10.0.0/16,Staff\nvlan,T,56,10.10.56.0/24,Students\n')


def test_admin_csrf_origin_checks(client):
    c,_=client
    auth=('admin','TESTPASSWORD_LONG_123456')
    payload={'host':'mail.example.test','port':25,'tls_mode':'none',
             'sender':'sender@example.org','recipients':'admins@example.org'}
    assert c.put('/api/admin/config/smtp',auth=auth,json=payload,
        headers={'Origin':'https://attacker.example','Sec-Fetch-Site':'cross-site'}).status_code==403
    assert c.put('/api/admin/config/smtp',auth=auth,json=payload,
        headers={'Origin':'https://testserver','Sec-Fetch-Site':'same-origin'}).status_code==200
    assert c.post('/api/admin/config/smtp/test',auth=auth,
        headers={'Origin':'https://attacker.example','Sec-Fetch-Site':'cross-site'}).status_code==403


def test_admin_network_lookup_and_ip_acl(client):
    c, settings=client
    admin=('admin','TESTPASSWORD_LONG_123456')
    r=c.get('/api/admin/config/lookup?ip=10.12.48.53',auth=admin)
    assert r.status_code==200
    assert r.json()['school']=='LNE' and r.json()['vlan']=='48'
    assert c.get('/api/admin/config/lookup?ip=8.8.8.8',auth=admin).status_code==422
    assert c.get('/api/admin/config/lookup?ip=garbage',auth=admin).status_code==422
    outside=TestClient(create_app(settings),base_url='https://testserver',client=('10.11.1.20',1234))
    assert outside.get('/api/admin/config/smtp',auth=admin).status_code==403
    assert outside.get('/api/identity').status_code==200


def test_plain_smtp_never_keeps_a_password(client):
    c,settings=client
    auth=('admin','TESTPASSWORD_LONG_123456')
    path='/api/admin/config/smtp'
    assert c.put(path,auth=auth,json={'host':'mail.test.local','tls_mode':'none',
               'password':'unsafe'}).status_code==422
    assert c.put(path,auth=auth,json={'host':'mail.test.local','tls_mode':'starttls',
               'password':'some-secret','sender':'speedtest@example.org',
               'recipients':'admin@example.org'}).status_code==200
    saved=c.put(path,auth=auth,json={'host':'127.0.0.1','port':25,'tls_mode':'none',
               'sender':'speedtest@example.org','recipients':'admin@example.org'})
    assert saved.status_code==200,saved.text
    assert saved.json()['password_configured'] is False
    assert 'some-secret' not in (Path(settings.db_path).parent/'managed'/'smtp.json').read_text()


def test_mapping_explanation_reports_exact_matches_not_guesses(client):
    c,_=client
    admin=('admin','TESTPASSWORD_LONG_123456')
    route='/api/admin/config/lookup'
    assert c.get(route+'?ip=10.12.48.53').status_code==401
    matched=c.get(route+'?ip=10.12.48.53',auth=admin)
    assert matched.status_code==200
    diag=matched.json()['mapping_diagnostics']
    assert diag['school_match']['cidr']=='10.12.0.0/16'
    assert diag['vlan_match']['cidr']=='10.12.48.0/21'
    missing=c.get(route+'?ip=10.64.241.15',auth=admin).json()
    assert missing['school']=='Unknown' and missing['vlan']=='Unknown'
    assert missing['mapping_diagnostics']['school_match'] is None
    assert 'No configured school or VLAN' in missing['mapping_diagnostics']['reason']
    import ipaddress
    with pytest.raises(ValueError):
        ipaddress.ip_network('10.64.241.0/21',strict=True)
    assert str(ipaddress.ip_network('10.64.241.0/21',strict=False))=='10.64.240.0/21'


def test_admin_focus_and_sort_apply_before_limit(client):
    from app.database import connect
    c,settings=client
    admin=('admin','TESTPASSWORD_LONG_123456')
    samples=[
       (1,'10.64.241.15','Unknown','Unknown',55.2,4.2,4.0),
       (2,'10.12.48.53','LNE','48',100.0,90.0,2.0),
       (3,'10.12.48.54','LNE','48',45.0,8.0,52.0),
       (4,'10.12.48.55','LNE','48',50.0,25.0,38.0),
    ]
    with connect(settings.db_path) as con:
        for timestamp,ip,school,vlan,down,up,jitter in samples:
            con.execute("""INSERT INTO results
              (completed_at,client_ip,school,vlan,network_label,agent_id,
               download_mbps,upload_mbps,latency_ms,jitter_ms,packet_loss_pct,
               download_bytes,upload_bytes,email_status)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (timestamp,ip,school,vlan,'Test','',down,up,7.0,jitter,0,100,100,'disabled'))
    url='/api/admin/results?limit=1&focus=unmapped'
    assert c.get(url).status_code==401
    one=c.get(url,auth=admin).json()
    assert one['matched_count']==1
    assert one['results'][0]['client_ip']=='10.64.241.15'
    jitter=c.get('/api/admin/results?focus=jitter&sort=jitter',auth=admin).json()
    assert jitter['matched_count']==2 and jitter['results'][0]['jitter_ms']==52.0
    upload=c.get('/api/admin/results?focus=upload&sort=upload',auth=admin).json()
    assert upload['matched_count']==2 and upload['results'][0]['upload_mbps']==4.2
    asym=c.get('/api/admin/results?focus=asymmetry&sort=ratio',auth=admin).json()
    assert asym['matched_count']==2 and asym['results'][0]['upload_mbps']==4.2
    assert c.get('/api/admin/results?focus=invalid',auth=admin).status_code==422
    assert c.get('/api/admin/results?sort=invalid',auth=admin).status_code==422
