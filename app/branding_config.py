"""Server-side, administrator-owned district branding. Persisted in the existing SQLite volume."""
from __future__ import annotations

import base64
import binascii
import struct

from .database import connect

MAX_PNG_BYTES = 450_000
DEFAULT_BRAND = {
    'org_name': 'GMCS',
    'site_name': 'GMCS Inside Speed Test',
    'tagline': 'NETWORK OPERATIONS',
    'heading': 'Inside Speed Test',
    'description': "Measure your school's connection to the GMCS-hosted test server. Results can help network administrators investigate performance across sites.",
}


def init_branding(db_path: str):
    with connect(db_path) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS site_branding (
          id INTEGER PRIMARY KEY CHECK(id=1), org_name TEXT NOT NULL,
          site_name TEXT NOT NULL, tagline TEXT NOT NULL,
          heading TEXT NOT NULL, description TEXT NOT NULL,
          logo_png BLOB
        )''')


def read_branding(db_path: str) -> dict:
    with connect(db_path) as con:
        row = con.execute('''SELECT org_name, site_name, tagline, heading, description,
          logo_png IS NOT NULL AS custom_logo FROM site_branding WHERE id=1''').fetchone()
    if row:
        output = dict(row)
        output['custom_logo'] = bool(output['custom_logo'])
        return output
    return {**DEFAULT_BRAND, 'custom_logo': False}


def write_branding(db_path: str, fields: dict):
    with connect(db_path) as con:
        con.execute('''INSERT INTO site_branding(id,org_name,site_name,tagline,heading,description)
          VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
          org_name=excluded.org_name, site_name=excluded.site_name,
          tagline=excluded.tagline, heading=excluded.heading,
          description=excluded.description''', tuple(fields[k] for k in DEFAULT_BRAND))
    return read_branding(db_path)


def read_logo(db_path: str) -> bytes | None:
    with connect(db_path) as con:
        row = con.execute('SELECT logo_png FROM site_branding WHERE id=1').fetchone()
    return row[0] if row else None


def store_logo(db_path: str, encoded: str):
    if not encoded.startswith('data:image/png;base64,'):
        raise ValueError('Upload a PNG image. The admin page converts JPEG/WebP safely.')
    raw = encoded[len('data:image/png;base64,'):]
    if len(raw) > 4 * ((MAX_PNG_BYTES + 2) // 3):
        raise ValueError('Logo is too large; maximum processed PNG is 450 KB')
    try:
        image = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('Invalid base64 PNG') from None
    if not (32 <= len(image) <= MAX_PNG_BYTES and
            image[:8] == b'\x89PNG\r\n\x1a\n' and
            image[12:16] == b'IHDR' and len(image) >= 33):
        raise ValueError('Invalid PNG structure or file size')
    w, h = struct.unpack('>II', image[16:24])
    if not (1 <= w <= 1200 and 1 <= h <= 600 and w * h <= 720000):
        raise ValueError('Invalid image dimensions. Maximum: 1200 x 600')
    # The file is only exposed as a browser image, never run or interpreted as code.
    # The administrator UI always re-encodes input through a canvas to strip metadata.
    with connect(db_path) as con:
        defaults = read_branding(db_path)
        con.execute('''INSERT OR IGNORE INTO site_branding(id,org_name,site_name,tagline,heading,description)
                       VALUES(1,?,?,?,?,?)''', tuple(defaults[k] for k in DEFAULT_BRAND))
        con.execute('UPDATE site_branding SET logo_png=? WHERE id=1', (image,))


def clear_logo(db_path: str):
    with connect(db_path) as con:
        con.execute('UPDATE site_branding SET logo_png=NULL WHERE id=1')
