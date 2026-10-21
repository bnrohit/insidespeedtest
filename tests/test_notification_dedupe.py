"""Ensure 100 test results in a shared VLAN trigger one notification only."""
import os
os.environ.setdefault('ADMIN_PASSWORD', 'TEST_ONLY_A_LONG_RANDOM_ADMIN_PASSWORD')
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from app.database import (claim_notification, connect, init_db,
                          notification_group, failed_notification)


def test_hundred_simultaneous_tests_create_one_notice_per_school_vlan(tmp_path):
    db = str(tmp_path / 'results.sqlite')
    init_db(db)
    with connect(db) as con:
        for i in range(1, 101):
            con.execute("""INSERT INTO results
               (id,completed_at,client_ip,school,vlan,network_label,download_mbps,
               upload_mbps,latency_ms,jitter_ms,packet_loss_pct,download_bytes,upload_bytes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (i, 1, f'10.10.1.{i}', 'EXAMPLE-HS', '48' if i <= 60 else '56',
                'Demo', 42.0, 43.0, 5.0, 1.0, 0.0, 100, 100))
    def test_one(i):
        group=notification_group({'school':'EXAMPLE-HS','vlan':'48' if i <= 60 else '56'}, f'10.10.1.{i}')
        return claim_notification(db, group, i, 86400)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results=list(pool.map(test_one, range(1, 101)))
    assert sum(results)==2
    with connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM results WHERE email_status='queued'").fetchone()[0]==2
        assert con.execute("SELECT COUNT(*) FROM results WHERE email_status='suppressed'").fetchone()[0]==98
        assert con.execute("SELECT COUNT(*) FROM notification_gates").fetchone()[0]==2


def test_grouping_unknown_ip_and_mail_fail_retry(tmp_path):
    db=str(tmp_path/'db.sqlite')
    init_db(db)
    a=notification_group({'school':'Unknown','vlan':'Unknown'}, '10.1.2.3')
    b=notification_group({'school':'Unknown','vlan':'Unknown'}, '10.1.2.4')
    assert a != b
    assert claim_notification(db,a,1,86400)
    assert not claim_notification(db,a,2,86400)
    assert claim_notification(db,b,3,86400)
    failed_notification(db,1,900)
    assert not claim_notification(db,a,4,86400)
    with connect(db) as con:
        con.execute('UPDATE notification_gates SET next_eligible_at=0 WHERE group_key=?',(a,))
    assert claim_notification(db,a,5,86400)


def test_session_global_and_per_vlan_capacity(tmp_path):
    from app.database import create_session
    db=str(tmp_path/'db.sqlite')
    init_db(db)
    for n in range(4):
        assert create_session(db,f'token{n}',f'10.1.2.{n+1}',30,6,
                              group_key='["EXAMPLE-HS","48",""]',max_active=5,
                              max_group_active=4)=='created'
    assert create_session(db,'token5','10.1.2.50',30,6,
                          group_key='["EXAMPLE-HS","48",""]',max_active=5,max_group_active=4)=='busy'
    assert create_session(db,'token6','10.1.4.60',30,6,
                          group_key='["EXAMPLE-HS","56",""]',max_active=5,max_group_active=4)=='created'
    assert create_session(db,'token7','10.1.5.70',30,6,
                          group_key='["OTHER-HS","48",""]',max_active=5,max_group_active=4)=='busy'
