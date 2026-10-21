#!/bin/sh
# Copy the client and install a disabled-until-configured systemd timer.
set -eu
if [ "$(id -u)" -ne 0 ]; then echo 'Run as root: sudo sh agent/install.sh' >&2; exit 1; fi
if ! command -v systemctl >/dev/null 2>&1; then echo 'systemd required' >&2; exit 1; fi
id gmcs-speedtest >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin gmcs-speedtest
install -d -m 0755 /opt/gmcs-speedtest
install -m 0755 agent/school_agent.py /opt/gmcs-speedtest/school_agent.py
install -d -m 0750 -o root -g gmcs-speedtest /etc/gmcs-speedtest
if [ ! -f /etc/gmcs-speedtest/agent.env ]; then
  install -m 0640 -o root -g gmcs-speedtest agent/agent.env.example /etc/gmcs-speedtest/agent.env
fi
# Do not invent credentials. Admin must securely provision token per server.
install -m 0644 agent/gmcs-speedtest.service /etc/systemd/system/gmcs-speedtest.service
install -m 0644 agent/gmcs-speedtest.timer /etc/systemd/system/gmcs-speedtest.timer
systemctl daemon-reload
printf '%s\n' 'Installed. Configure /etc/gmcs-speedtest/agent.env and token (chmod 640 root:gmcs-speedtest) before enabling:' \
 '  sudo systemctl enable --now gmcs-speedtest.timer' \
 '  sudo systemctl start gmcs-speedtest.service' \
 '  journalctl -u gmcs-speedtest.service -n 30 --no-pager'
