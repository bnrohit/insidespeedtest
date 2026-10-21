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
                      agents_path=str(agents),admin_username='admin',admin_password='TESTPASSWORD_LONG_123456')
    app=create_app(settings)
    return TestClient(app,base_url='https://testserver',client=('10.12.48.50',4444)),settings


def test_admin_only_and_persistent_smtp(client):
    c,settings=client
    path='/api/admin/config/smtp'
    assert c.get(path).status_code==401
    assert c.put(path,json={'host':'mail.test.local'}).status_code==401
    admin=('admin','TESTPASSWORD_LONG_123456')
    response=c.put(path,auth=admin,json={'host':'10.250.32.28','port':25,'tls_mode':'none',
                           'username':'','sender':'speedtest@example.org','recipients':'noc@example.org',
                           'password':'SOME-LOCAL-SECRET','dedupe_seconds':86400,
                           'email_agent_results':True,'email_browser_results':True})
    assert response.status_code==200,response.text
    assert 'SOME-LOCAL-SECRET' not in response.text
    assert response.json()['password_configured']
    assert c.get(path,auth=admin).json()['host']=='10.250.32.28'
    cfgfile=Path(settings.db_path).parent/'managed'/'smtp.json'
    assert cfgfile.exists() and cfgfile.stat().st_mode & 0o077==0
    after_restart=TestClient(create_app(settings),base_url='https://testserver',client=('10.12.48.50',4444))
    assert after_restart.get(path,auth=admin).json()['host']=='10.250.32.28'
    assert after_restart.get(path,auth=admin).json()['password_configured'] is True
    assert c.put(path,auth=admin,json={'host':'10.250.32.28','port':25,'tls_mode':'none','username':'login'}).status_code==422
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