"""Regression: time aggregation, status semantics, bounded import and history retention."""
import csv
import importlib.util
import io
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from app import router_history as h

NOW=1_815_000_000

def row(site='CDE',status='TEST_COMPLETE',up='29.2',down='28.4'):
    return {'site':site,'name':'School','router_ip':'10.21.8.10','classification':'school',
            'inventory_status':'candidate','status':status,'ping_loss_percent':'0',
            'avg_latency_ms':'1.3','upload_mbps_capped':up,
            'download_mbps_capped':down,'comment':''}


def test_import_and_query(tmp_path):
    db=str(tmp_path/'test.sqlite3')
    assert h.import_rows(db,[row()],NOW,30)==1
    latest=h.latest(db)
    assert latest[0]['down_mbps']==28.4
    assert latest[0]['cap_mbps']==30
    assert h.trend(db,'CDE','day',NOW+100)['points'][0]['down_mbps']==28.4
    failed=row('CDE','SSH_UNREACHABLE','','')
    assert h.import_rows(db,[failed],NOW+3600,30)==1
    samples=h.trend(db,'CDE','day',NOW+3601)['points']
    assert len(samples)==2
    assert samples[-1]['down_mbps'] is None
    assert samples[-1]['missing']==1
    assert h.latest_site(db,'CDE')['status']=='SSH_UNREACHABLE'


def test_injection_and_invalid_rejected(tmp_path):
    db=str(tmp_path/'test.sqlite3')
    for bad in [row('DROP TABLE'),row('CDE')|{'router_ip':'8.8.8.8'}]:
        with pytest.raises(ValueError):h.import_rows(db,[bad],NOW,30)
    with pytest.raises(ValueError):h.import_rows(db,[row(),row()],NOW,30)
    with pytest.raises(ValueError):h.trend(db,'CDE','all',NOW)


def test_retention_two_years(tmp_path):
    db=str(tmp_path/'test.sqlite3')
    h.import_rows(db,[row()],NOW-734*86400,30)
    h.import_rows(db,[row('CDE','TEST_COMPLETE','30','30')],NOW,30)
    assert len(h.trend(db,'CDE','2years',NOW)['points'])==1
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM vyos_hourly').fetchone()[0]==1


def test_runner_merge_status():
    p=Path(__file__).resolve().parents[1]/'integrations'/'vyos-hourly'/'run_hourly.py'
    spec=importlib.util.spec_from_file_location('hourly',p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    candidates=[row('CDE'),row('GPH')|{'site':'GPH','router_ip':'10.4.8.10'},
                row('TOH')|{'site':'TOH','router_ip':'10.51.8.10','inventory_status':'needs_verification'},
                row('SHP')|{'site':'SHP','router_ip':'10.200.8.10','classification':'infrastructure'}]
    data=module.merge_inventory(candidates,[candidates[0]],['CDE'])
    assert [x['status'] for x in data]==['TEST_COMPLETE','NOT_ENROLLED','NEEDS_VERIFICATION','SKIPPED_INFRA']


def test_librenms_plugin_outage_and_perfdata(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('plugin',Path(__file__).resolve().parents[1]/'integrations'/'librenms'/'check_gmcs_router.py')
    plugin=importlib.util.module_from_spec(spec);spec.loader.exec_module(plugin)
    token=tmp_path/'token';token.write_text('t'*48)
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return b''
    class FakeResponse:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return json.dumps({'site':'CDE','at':NOW,'status':'TEST_COMPLETE','down_mbps':29.4,'up_mbps':29.1,'latency_ms':1.4,'ping_loss':0}).encode()
    # json.load() calls .read() with no arguments.
    monkeypatch.setattr(plugin.urllib.request,'urlopen',lambda *a,**kw:FakeResponse())
    status,msg=plugin.check('CDE','https://gmcs.example',str(token),now=NOW+120)
    assert status==0 and 'download_mbps=29.400Mbps' in msg
    assert plugin.check('CDE;rm','https://gmcs.example',str(token),now=NOW)[0]==3
    assert plugin.check('CDE','http://gmcs.example',str(token),now=NOW)[0]==3
    assert plugin.check('CDE','https://gmcs.example',str(token),now=NOW+3*3600)[0]==3
