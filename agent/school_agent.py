#!/usr/bin/env python3
"""Dependency-free, authenticated internal speed test for VyOS routers or Linux school hosts.

Only reports to the configured HTTPS GMCS service; the GMCS server emails admins.
Use the school VM's trusted district CA (optionally via SPEEDTEST_CA_FILE).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError('Refusing redirect during authenticated network measurement')


def open_url(opener, url: str, *, method='GET', headers=None, data=None, timeout=30):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    return opener.open(req, timeout=timeout)


def run(args):
    base = args.url.rstrip('/')
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/') or parsed.params:
        raise ValueError('SPEEDTEST_URL must be a plain https:// hostname (optional port), without path, credentials or query')
    token_file = Path(args.token_file)
    stat = token_file.stat()
    if stat.st_mode & 0o007:
        raise ValueError('Agent key file is accessible to other users (chmod 640 or 600 required)')
    agent_key = token_file.read_text(encoding='utf-8').strip()
    if len(agent_key) < 32:
        raise ValueError('Agent key must contain at least 32 characters')
    ctx = ssl.create_default_context(cafile=args.ca_file or None)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), NoRedirect())

    def endpoint(path):
        return base + path

    with open_url(opener, endpoint('/api/session'), method='POST',
                  headers={'X-Agent-Id': args.agent_id, 'X-Agent-Key': agent_key}, data=b'', timeout=20) as response:
        session = json.load(response)
    if session.get('agent_id') != args.agent_id:
        raise ValueError('Server did not confirm agent identity')
    token = session['token']
    headers = {'X-Speedtest-Token': token}
    identity = session['identity']

    pings = []
    fails = 0
    for index in range(8):
        t0 = time.monotonic()
        try:
            with open_url(opener, endpoint('/api/ping') + '?p=' + str(index), headers=headers, timeout=5) as response:
                response.read()
            pings.append((time.monotonic() - t0) * 1000)
        except (OSError, urllib.error.URLError, ValueError):
            fails += 1
        time.sleep(0.08)
    if not pings:
        raise RuntimeError('All latency probes failed')
    latency = sum(pings) / len(pings)
    jitter = sum(abs(b-a) for a,b in zip(pings, pings[1:])) / max(1, len(pings)-1)

    def measure(direction: str, seconds: float, mib_limit: int, chunk_mib: int):
        block = chunk_mib * 1048576
        payload = os.urandom(block) if direction == 'upload' else None
        started = time.monotonic()
        transferred = 0
        while transferred + block <= mib_limit * 1048576:
            if transferred and time.monotonic() - started >= seconds:
                break
            if direction == 'download':
                url = endpoint('/api/download') + '?bytes=' + str(block)
                with open_url(opener, url, headers=headers, timeout=args.request_timeout) as response:
                    read_bytes = 0
                    while True:
                        piece = response.read(262144)
                        if not piece:
                            break
                        read_bytes += len(piece)
                    if read_bytes != block:
                        raise RuntimeError('Incomplete download')
                transferred += read_bytes
            else:
                with open_url(opener, endpoint('/api/upload'), method='POST',
                              headers={**headers, 'Content-Type': 'application/octet-stream'},
                              data=payload, timeout=args.request_timeout) as response:
                    accepted = json.load(response)['bytes_received']
                if accepted != block:
                    raise RuntimeError('Incomplete upload')
                transferred += accepted
        elapsed = time.monotonic() - started
        if transferred <= 0:
            raise RuntimeError('No transfer measurement completed')
        return round(transferred * 8 / elapsed / 1_000_000, 3), transferred

    down, down_bytes = measure('download', args.download_seconds, args.download_max_mib, args.chunk_mib)
    up, up_bytes = measure('upload', args.upload_seconds, args.upload_max_mib, args.chunk_mib)
    report = {
        'token': token, 'download_mbps': down, 'upload_mbps': up,
        'latency_ms': latency, 'jitter_ms': jitter, 'packet_loss_pct': 100 * fails / 8,
        'download_bytes': down_bytes, 'upload_bytes': up_bytes,
    }
    with open_url(opener, endpoint('/api/results'), method='POST',
                  headers={'Content-Type': 'application/json'},
                  data=json.dumps(report).encode('utf-8'), timeout=20) as response:
        ack = json.load(response)
    if ack.get('agent_id') != args.agent_id:
        raise ValueError('Server report identity mismatch')
    print(json.dumps({'result_id': ack['result_id'], 'agent_id': args.agent_id,
                      'school': ack['school'], 'vlan': ack['vlan'],
                      'observed_ip': identity['client_ip'],
                      'download_mbps': down, 'upload_mbps': up,
                      'latency_ms': round(latency, 2), 'jitter_ms': round(jitter, 2),
                      'email_notification': ack['email_notification']}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='GMCS inside network scheduled speed test')
    parser.add_argument('--url', default=os.getenv('SPEEDTEST_URL', ''), required=False)
    parser.add_argument('--agent-id', default=os.getenv('SPEEDTEST_AGENT_ID', ''), required=False)
    parser.add_argument('--token-file', default=os.getenv('SPEEDTEST_TOKEN_FILE', '/etc/gmcs-speedtest/token'))
    parser.add_argument('--ca-file', default=os.getenv('SPEEDTEST_CA_FILE', ''))
    parser.add_argument('--download-seconds', type=float, default=5.0)
    parser.add_argument('--upload-seconds', type=float, default=4.0)
    parser.add_argument('--download-max-mib', type=int, default=96)
    parser.add_argument('--upload-max-mib', type=int, default=24)
    parser.add_argument('--chunk-mib', type=int, default=4)
    parser.add_argument('--request-timeout', type=int, default=45)
    args = parser.parse_args(argv)
    if not args.url or not args.agent_id or any((i < 1 for i in (args.download_max_mib, args.upload_max_mib, args.chunk_mib))):
        parser.error('SPEEDTEST_URL, SPEEDTEST_AGENT_ID, and positive MiB values are required')
    if args.chunk_mib > 8 or args.chunk_mib > min(args.upload_max_mib, args.download_max_mib):
        parser.error('Chunk size must fit both transfer limits and be at most 8 MiB')
    if not 0.5 <= args.download_seconds <= 120 or not 0.5 <= args.upload_seconds <= 120:
        parser.error('Test seconds must be 0.5-120')
    if args.download_max_mib + args.upload_max_mib > 384:
        parser.error('Test cannot exceed server 384 MiB default session budget')
    try:
        return run(args)
    except (OSError, ValueError, RuntimeError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        print(f'GMCS speed test failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
