"""Regression tests for bounded, parameterized transfer reservations."""
from app.database import connect, create_session, init_db, reserve_transfer


def test_download_upload_reservations_and_total_limit(tmp_path):
    db = str(tmp_path / "reservations.sqlite")
    init_db(db)
    ip = "10.44.1.42"
    token = "test-token"
    assert create_session(db, token, ip, 0, 10, group_key="test") == "created"

    assert reserve_transfer(db, token, ip, 1024, "download", 2048, 1536)
    assert not reserve_transfer(db, token, ip, 600, "download", 2048, 1536)
    assert reserve_transfer(db, token, ip, 512, "upload", 2048, 1536)
    assert not reserve_transfer(db, token, ip, 600, "upload", 2048, 1536)

    with connect(db) as con:
        row = con.execute(
            "SELECT download_reserved, upload_reserved FROM sessions WHERE token_hash=?",
            (token,),
        ).fetchone()
        assert tuple(row) == (1024, 512)


def test_invalid_direction_and_identity_cannot_reserve(tmp_path):
    db = str(tmp_path / "reservations.sqlite")
    init_db(db)
    assert create_session(db, "token", "10.44.1.42", 0, 10) == "created"
    for direction in ("download; DROP TABLE sessions", "neither", ""):
        assert not reserve_transfer(db, "token", "10.44.1.42", 10, direction, 100, 100)
    assert not reserve_transfer(db, "token", "10.44.1.42", 0, "download", 100, 100)
    assert not reserve_transfer(db, "token", "10.44.1.43", 10, "download", 100, 100)
    assert not reserve_transfer(db, "bad-token", "10.44.1.42", 10, "upload", 100, 100)
