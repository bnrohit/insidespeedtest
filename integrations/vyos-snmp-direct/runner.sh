#!/bin/sh
# VyOS task-scheduler executes this locally. Scheduled test, not SNMP poll, causes traffic.
set -eu
umask 077
exec /usr/bin/flock -n /run/lock/gmcs-vyos-snmp-speedtest.lock \
  /usr/bin/nice -n 10 /usr/bin/python3 \
  /config/scripts/gmcs-vyos-speedtest/collect.py
