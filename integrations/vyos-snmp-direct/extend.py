#!/usr/bin/env python3
"""Nonprivileged, read-only SNMP extend: print cached safe metrics, NEVER launch tests."""
import json
import math
import sys
import time
from pathlib import Path

DEFAULT = Path('/config/user-data/gmcs-vyos-speedtest/latest.json')
NAMES = ('download_mbps', 'upload_mbps', 'latency_ms', 'jitter_ms', 'loss_pct')


def render(cache=DEFAULT, now=None):
    t = int(time.time()) if now is None else now
    obj = {'version': 1, 'error': 0, 'errorString': '', 'data': {}}
    try:
        data = json.loads(Path(cache).read_text(encoding='utf-8'))
        timestamp = int(data['at'])
        for source in ('inside', 'ookla'):
            sample = data.get(source) or {}
            status = str(sample.get('status', 'missing'))[:16]
            # Never repeat measurements indefinitely when an hourly test stops.
            fresh = -60 <= t - timestamp <= 9000
            values = {'status': status if fresh else 'stale', 'at': timestamp}
            for name in NAMES:
                x = sample.get(name)
                if (fresh and status == 'ok' and type(x) in (float, int)
                        and math.isfinite(x) and 0 <= x <= 100000):
                    values[name] = x
                else:
                    values[name] = None
            obj['data'][source] = values
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        for source in ('inside', 'ookla'):
            obj['data'][source] = {'status': 'missing', 'at': 0,
                                   **{name: None for name in NAMES}}
    return json.dumps(obj, separators=(',', ':'), allow_nan=False)


if __name__ == '__main__':
    print(render(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT))
