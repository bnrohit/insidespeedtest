"""School-side VyOS agent / LibreNMS device integration regression."""
import importlib.util
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_vyos_installer_and_runner_syntax():
    for path in ('agent/vyos/install-vyos.sh', 'agent/vyos/runner.sh'):
        subprocess.run(['/bin/sh', '-n', str(ROOT / path)], check=True)
    runner = (ROOT / 'agent/vyos/runner.sh').read_text()
    installer = (ROOT / 'agent/vyos/install-vyos.sh').read_text()
    assert '/config/scripts/gmcs-speedtest/school_agent.py' in runner
    assert 'flock -n' in runner
    assert '--download-max-mib 24' in runner
    assert 'NO ROUTER CONFIGURATION CHANGED' in installer
    assert 'crontab-spec' in installer
    assert 'chmod 0600' in installer


def test_librenms_accepts_router_hostname_argument(monkeypatch, capsys):
    path = ROOT / 'integrations/librenms/check_gmcs_school_agent.py'
    spec = importlib.util.spec_from_file_location('gmcs_vyos_librenms_plugin', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = []

    def fake_check(agent_id, url, token_file, ca_file=None, now=None):
        seen.append((agent_id, url, token_file, ca_file))
        return 0, 'OK - cached sample | download_mbps=12.000;;;0;'

    monkeypatch.setattr(module, 'check', fake_check)
    monkeypatch.setattr(sys, 'argv', ['check_gmcs_school_agent.py', '-H', '10.21.1.1',
                                    '--agent-id', 'CDE-VYOS01', '--url', 'https://noc.gmcs.test:18443',
                                    '--token-file', '/etc/librenms/token'])
    assert module.main() == 0
    assert seen == [('CDE-VYOS01', 'https://noc.gmcs.test:18443', '/etc/librenms/token', None)]
    assert 'download_mbps=12.000;;;0;' in capsys.readouterr().out


def test_nagios_data_units_are_librenms_compatible():
    src = (ROOT / 'integrations/librenms/check_gmcs_school_agent.py').read_text()
    assert "d['download_mbps']:.3f};;;" in src
    assert "d['upload_mbps']:.3f};;;" in src
    assert "d['download_mbps']:.3f}Mbps" not in src
    assert "d['upload_mbps']:.3f}Mbps" not in src
