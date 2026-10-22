"""Security regressions for persistent admin branding and bounded external egress."""
import base64
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import Settings, create_app


def setup(tmp_path):
    mapping=tmp_path/'networks.csv'
    mapping.write_text('scope,school,vlan,cidr,label\nschool,GPHS,,10.44.0.0/20,GPHS Campus\n')
    settings=Settings(db_path=str(tmp_path/'results.sqlite3'),mapping_path=str(mapping),
         admin_username='gmcsadmin',admin_password='example-long-private-password',
         admin_client_cidrs='10.0.0.0/8')
    app=create_app(settings)
    def client(): return TestClient(app,base_url='https://speedtest.test',client=('10.44.1.50',40000))
    return settings, client(), client()


def login(c):
    assert c.post('/api/admin/login',json={'username':'gmcsadmin',
       'password':'example-long-private-password'}).status_code==204
    return {'X-CSRF-Token':c.get('/api/admin/session').json()['csrf_token']}


def test_branding_persistent_permission_csrf_and_logo(tmp_path):
    settings,c,guest=setup(tmp_path)
    payload={'org_name':'Demo School','site_name':'Demo District Test',
             'tagline':'Technology Operations','heading':'Network Health',
             'description':'Check connectivity inside our schools.'}
    assert c.get('/api/branding').json()['org_name']=='GMCS'
    assert c.put('/api/admin/branding',json=payload).status_code==401
    h=login(c)
    assert c.put('/api/admin/branding',json=payload).status_code==403
    assert c.put('/api/admin/branding',json=payload,headers=h).status_code==200
    assert guest.get('/api/branding').json()['org_name']=='Demo School'
    assert guest.get('/api/branding').json()['site_name']=='Demo District Test'
    assert c.put('/api/admin/branding',json={**payload,'heading':'X\nScript'},headers=h).status_code==422
    assert c.put('/api/admin/branding/logo',json={'png_data':'data:image/svg+xml;base64,AAAA'},headers=h).status_code==422
    png=Path('app/static/gmcs-logo.png').read_bytes()
    r=c.put('/api/admin/branding/logo',json={'png_data':'data:image/png;base64,'+base64.b64encode(png).decode()},headers=h)
    assert r.status_code==200, r.text
    assert guest.get('/api/branding').json()['custom_logo'] is True
    assert guest.get('/api/branding/logo').content==png
    assert c.delete('/api/admin/branding/logo').status_code==403
    assert c.delete('/api/admin/branding/logo',headers=h).status_code==200
    assert guest.get('/api/branding').json()['custom_logo'] is False
    # Persistence across web-app restart: same existing sqlite volume.
    new=TestClient(create_app(settings),base_url='https://speedtest.test',client=('10.44.1.50',40000))
    assert new.get('/api/branding').json()['heading']=='Network Health'


def test_egress_admin_only_and_global_cooldown(tmp_path, monkeypatch):
    settings,c,guest=setup(tmp_path)
    assert guest.get('/api/admin/diagnostics/egress').status_code==401
    assert guest.post('/api/admin/diagnostics/egress').status_code==401
    h=login(c)
    assert c.post('/api/admin/diagnostics/egress').status_code==403
    import app.external_diag as eg
    monkeypatch.setattr(eg,'_resolve_public_ip',lambda:('1.1.1.1',2.5))
    def fake_transfer(ip,method,target,size):
        assert ip=='1.1.1.1'
        if method=='GET': assert target=='/__down?bytes=4194304'; return (22.5,9.8)
        assert target=='/__up'; return (11.5,8.3)
    monkeypatch.setattr(eg,'_transfer',fake_transfer)
    r=c.post('/api/admin/diagnostics/egress',headers=h)
    assert r.status_code==200,r.text
    assert r.json()['download_mbps']==22.5
    assert r.json()['upload_mbps']==11.5
    assert c.post('/api/admin/diagnostics/egress',headers=h).status_code==429
    assert len(c.get('/api/admin/diagnostics/egress').json()['samples'])==1


def test_egress_rejects_private_dns(tmp_path,monkeypatch):
    import app.external_diag as eg
    monkeypatch.setattr(eg.socket,'getaddrinfo',lambda *args:[(2,1,0,'',('10.0.0.1',443))])
    try:
        eg._resolve_public_ip()
        assert False,'unsafe DNS should not pass'
    except OSError as exc:
        assert 'private' in str(exc)
