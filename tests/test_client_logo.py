"""District branding is server-controlled; visitors never edit the logo."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import Settings, create_app


def test_default_branding_read_only_for_visitors(tmp_path):
    mapping = tmp_path / 'networks.csv'
    mapping.write_text('scope,school,vlan,cidr,label\nschool,GPHS,,10.44.0.0/20,GPHS Campus\n')
    settings = Settings(db_path=str(tmp_path / 'results.db'), mapping_path=str(mapping),
                        admin_username='gmcsadmin', admin_password='example-long-private-password',
                        allowed_client_cidrs='10.0.0.0/8', admin_client_cidrs='10.0.0.0/8')
    c = TestClient(create_app(settings), base_url='https://speedtest.test', client=('10.44.1.50', 40000))
    page = c.get('/')
    assert page.status_code == 200
    assert 'id="brand-logo"' in page.text
    assert 'brand-upload-button' not in page.text
    assert 'brand-logo-file' not in page.text
    assert 'localStorage' not in c.get('/static/branding.js').text
    assert '/api/branding/logo' in page.text
    image = c.get('/api/branding/logo')
    assert image.status_code == 200
    assert image.headers['content-type'].startswith('image/png')
    assert image.content.startswith(b'\x89PNG\r\n\x1a\n')
    assert c.get('/api/branding').json()['org_name'] == 'GMCS'
    assert c.put('/api/admin/branding',json={'org_name':'Unauthorized'}).status_code == 401
    assert c.put('/api/admin/branding/logo',json={'png_data':'nothing'}).status_code == 401


def test_upgrade_allowlist_tracks_branding_and_egress():
    base = Path(__file__).resolve().parents[1]
    upgrade = (base / 'deploy/gmcs-safe-upgrade.sh').read_text()
    for f in ['app/static/index.html', 'app/static/style.css','app/static/admin.js',
              'app/static/gmcs-logo.png', 'app/static/branding.js',
              'app/branding_config.py','app/external_diag.py']:
        assert f in upgrade
