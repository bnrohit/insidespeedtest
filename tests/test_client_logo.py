"""Public clients may customize logos locally without any new server upload surface."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import Settings, create_app


def test_gmcs_default_logo_and_picker(tmp_path):
    mapping = tmp_path / 'networks.csv'
    mapping.write_text('scope,school,vlan,cidr,label\nschool,GPHS,,10.44.0.0/20,GPHS Campus\n')
    settings = Settings(db_path=str(tmp_path / 'results.db'), mapping_path=str(mapping),
                        admin_username='gmcsadmin', admin_password='example-long-private-password',
                        allowed_client_cidrs='10.0.0.0/8', admin_client_cidrs='10.0.0.0/8')
    c = TestClient(create_app(settings), base_url='https://speedtest.test', client=('10.44.1.50', 40000))
    page = c.get('/')
    assert page.status_code == 200
    assert 'id="brand-logo"' in page.text
    assert 'id="brand-upload-button"' in page.text
    assert 'id="brand-reset-button"' in page.text
    assert 'type="file" accept="image/png,image/jpeg,image/webp"' in page.text
    assert '/static/branding.js' in page.text
    assert 'this browser' in page.text
    image = c.get('/static/gmcs-logo.png')
    assert image.status_code == 200
    assert image.headers['content-type'].startswith('image/png')
    assert image.content.startswith(b'\x89PNG\r\n\x1a\n')
    assert c.get('/static/branding.js').status_code == 200
    # No client-logo upload backend: files are stored exclusively in the browser.
    assert c.post('/api/client/logo', files={'file':('bad.svg',b'<svg></svg>','image/svg+xml')}).status_code == 404


def test_upgrade_allowlist_tracks_all_logo_assets():
    base = Path(__file__).resolve().parents[1]
    upgrade = (base / 'deploy/gmcs-safe-upgrade.sh').read_text()
    for f in ['app/static/index.html', 'app/static/style.css',
              'app/static/gmcs-logo.png', 'app/static/branding.js']:
        assert f in upgrade
