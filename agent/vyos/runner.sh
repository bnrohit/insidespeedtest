#!/bin/sh
# VyOS persistent on-router agent runner. Task-scheduler executes this as root.
# Configuration and credentials remain on the router, never in the repository.
set -eu
umask 077
CFG=/config/auth/gmcs-speedtest/agent.env
KEY=/config/auth/gmcs-speedtest/token
if [ ! -r "$CFG" ] || [ ! -r "$KEY" ]; then
  echo 'GMCS VyOS agent not configured: missing agent.env or token' >&2
  exit 2
fi
# No untrusted user data reaches this file; only the VyOS root admin provisions it.
# shellcheck disable=SC1090
. "$CFG"
: "${SPEEDTEST_URL:?Missing SPEEDTEST_URL}"
: "${SPEEDTEST_AGENT_ID:?Missing SPEEDTEST_AGENT_ID}"
export SPEEDTEST_URL SPEEDTEST_AGENT_ID
export SPEEDTEST_TOKEN_FILE="$KEY"
export SPEEDTEST_CA_FILE="${SPEEDTEST_CA_FILE:-}"
# Fail fast if an older run has not finished. Avoid saturating router CPU or WAN.
exec /usr/bin/flock -n /run/lock/gmcs-speedtest-vyos.lock \
  /usr/bin/nice -n 10 /usr/bin/python3 \
  /config/scripts/gmcs-speedtest/school_agent.py \
  --download-seconds 4 --upload-seconds 3 \
  --download-max-mib 24 --upload-max-mib 8 --chunk-mib 2 \
  --request-timeout 25
