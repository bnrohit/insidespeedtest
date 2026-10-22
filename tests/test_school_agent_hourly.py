"""School-host tests are independent of VyOS router collection and LibreNMS polling."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import time

from fastapi.testclient import TestClient

from app.main import Settings, create_app
from app.school_agent_history import listed, most_recent, graph

ROOT=Path(__file__).resolve().parents[1]


def setup(tmp_path):
    mapping=tmp_path/'networks.csv'
    mapping.write_text('scope,school,vlan,cidr,label\nschool,CDE,,10.21.0.0/20,Campus\n')
    token='TEST_SCHOOL_HOST_TOKEN_'+'X'*48
    agents=tmp_path/'agents.csv'
    agents.write_text('agent_id,token_sha256,allowed_cidr\nCDE-CACHE01,'+
                      hashlib.sha256(token.encode()).hexdigest()+',10.21.1.25/32\n')
    cfg=Settings(db_path=str(tmp_path/'results.sqlite3'),mapping_path=str(mapping),
                 agents_path=str(agents), admin_username='admin',
                 admin_password='APP_TEST_LONG_ADMIN_PASSWORD_UNRELATED',
                 admin_client_cidrs='10.0.0.0/8')
    app=create_app(cfg)
    client=TestClient(app,base_url='https://gmcs.test',client=('10.21.1.25',4321))
    return cfg,client,token


def insert_sample(db,when,agent_id='CDE-CACHE01'):
    with sqlite3.connect(db) as con:
        con.execute('''INSERT INTO results(completed_at,client_ip,school,vlan,network_label,agent_id,
            download_mbps,upload_mbps,latency_ms,jitter_ms,packet_loss_pct,download_bytes,upload_bytes)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (when,'10.21.1.25','CDE','48','Staff',agent_id,29.5,18.1,2.4,1.1,0.0,4194304,4194304))


def test_site_hosts_reporting_history_and_admin_auth(tmp_path):
    cfg,client,token=setup(tmp_path)
    now=int(time.time())
    assert client.get('/api/admin/school-agents').status_code==401
    assert client.get('/api/monitoring/school-agent/CDE-CACHE01').status_code==503
    assert listed(cfg.db_path,['CDE-CACHE01'],now)[0]['status']=='NO_SAMPLE'
    insert_sample(cfg.db_path,now-400)
    assert most_recent(cfg.db_path,'CDE-CACHE01',now)['status']=='REPORTING'
    g=graph(cfg.db_path,'CDE-CACHE01','day',now)
    assert g['points'][0]['down_mbps']==29.5
    assert g['retention_days']>=730
    with sqlite3.connect(cfg.db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM vyos_hourly").fetchone()[0]==0
    p=tmp_path/'gmcs-monitoring.token';p.write_text('Z'*48)
    assert client.get('/api/monitoring/school-agent/CDE-CACHE01').status_code==401
    reply=client.get('/api/monitoring/school-agent/CDE-CACHE01',headers={'Authorization':'Bearer '+'Z'*48})
    assert reply.status_code==200 and reply.json()['agent_id']=='CDE-CACHE01'
    assert 'client_ip' not in reply.json() and 'hostname' not in reply.text
    assert client.get('/api/monitoring/school-agent/INVALID',headers={'Authorization':'Bearer '+'Z'*48}).status_code==404
    assert client.post('/api/admin/login',json={'username':'admin','password':cfg.admin_password}).status_code==204
    assert client.get('/api/admin/school-agents').json()['agents'][0]['status']=='REPORTING'
    assert client.get('/api/admin/school-agents/CDE-CACHE01?window=2years').status_code==200
    assert client.get('/api/admin/school-agents/CDE-CACHE01?window=invalid').status_code==400
    assert client.get('/api/admin/school-agents/ROGUE?window=day').status_code==404


def test_stale_and_reject_insecure_monitoring(tmp_path):
    cfg,client,token=setup(tmp_path)
    old=int(time.time())-11000
    insert_sample(cfg.db_path,old)
    assert most_recent(cfg.db_path,'CDE-CACHE01')['status']=='STALE'
    (tmp_path/'gmcs-monitoring.token').write_text('Z'*48)
    insecure=TestClient(client.app,base_url='http://gmcs.test',client=('10.21.1.25',1234))
    assert insecure.get('/api/monitoring/school-agent/CDE-CACHE01',headers={'Authorization':'Bearer '+'Z'*48}).status_code==403


def test_existing_source_ip_bound_agent_start(tmp_path):
    cfg,client,token=setup(tmp_path)
    ok=client.post('/api/session',headers={'X-Agent-Id':'CDE-CACHE01','X-Agent-Key':token})
    assert ok.status_code==200 and ok.json()['agent_id']=='CDE-CACHE01'
    untrusted=TestClient(client.app,base_url='https://gmcs.test',client=('10.21.1.26',4321))
    no=untrusted.post('/api/session',headers={'X-Agent-Id':'CDE-CACHE01','X-Agent-Key':token})
    assert no.status_code==401


def test_librenms_reads_cached_sample_and_never_executes_test(tmp_path,monkeypatch):
    path=ROOT/'integrations/librenms/check_gmcs_school_agent.py'
    spec=importlib.util.spec_from_file_location('school_plugin',path)
    plugin=importlib.util.module_from_spec(spec);spec.loader.exec_module(plugin)
    tokenfile=tmp_path/'secret';tokenfile.write_text('Z'*48)
    now=int(time.time())
    class FakeResponse:
        status=200
        def read(self,limit):
            assert limit==8193
            return json.dumps({'agent_id':'CDE-CACHE01','at':now-5,'status':'REPORTING',
                 'school':'CDE','download_mbps':29.5,'upload_mbps':18.1,
                 'latency_ms':2.4,'jitter_ms':1.1,'loss_pct':0}).encode()
    class FakeConnection:
        def __init__(self,*args,**kwargs):pass
        def request(self,method,url,headers):
            assert method=='GET' and url=='/api/monitoring/school-agent/CDE-CACHE01'
            assert headers['Authorization']=='Bearer '+'Z'*48
        def getresponse(self):return FakeResponse()
        def close(self):pass
    monkeypatch.setattr(plugin.http.client,'HTTPSConnection',FakeConnection)
    code,message=plugin.check('CDE-CACHE01','https://gmcs.test:18443',str(tokenfile),now=now)
    assert code==0 and 'download_mbps=29.500;;;0;'  in message
    assert plugin.check('CDE-CACHE01','http://gmcs.test',str(tokenfile),now=now)[0]==3
    assert plugin.check('CDE-CACHE01/../../a','https://gmcs.test',str(tokenfile),now=now)[0]==3
