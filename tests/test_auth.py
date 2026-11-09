"""登录闸门。"""

from __future__ import annotations


def test_gate_blocks_anonymous(client):
    res = client.get("/api/apps")
    assert res.status_code == 401


def test_login_wrong_password(admin):
    res = admin.post("/api/auth/login", json={"username": "", "password": "nope"})
    assert res.status_code == 401
    assert res.json()["error"] == "invalid_credentials"


def test_login_success_sets_cookie(client):
    res = client.post("/api/auth/login", json={"username": "", "password": "secret"})
    assert res.status_code == 200
    assert "wxpush_session" in res.cookies or "wxpush_session" in client.cookies


def test_session_endpoint(client):
    assert client.get("/api/auth/session").json()["authenticated"] is False
    client.post("/api/auth/login", json={"username": "", "password": "secret"})
    info = client.get("/api/auth/session").json()
    assert info["authenticated"] is True
    assert info["gate"] is True


def test_logout(admin):
    admin.post("/api/auth/logout")
    assert admin.get("/api/apps").status_code == 401


def test_username_required_when_configured(tmp_path):
    from fastapi.testclient import TestClient

    from wxpush.app import create_app
    from wxpush.config import Settings

    settings = Settings(
        data_dir=tmp_path / "data", admin_user="bob", admin_password="pw"
    )
    with TestClient(create_app(settings)) as client:
        bad = client.post("/api/auth/login", json={"username": "alice", "password": "pw"})
        assert bad.status_code == 401
        good = client.post("/api/auth/login", json={"username": "bob", "password": "pw"})
        assert good.status_code == 200


def test_no_password_means_open(tmp_path):
    from fastapi.testclient import TestClient

    from wxpush.app import create_app
    from wxpush.config import Settings

    with TestClient(create_app(Settings(data_dir=tmp_path / "data"))) as client:
        assert client.get("/api/apps").status_code == 200
        info = client.get("/api/auth/session").json()
        assert info["gate"] is False
        assert info["authenticated"] is True


def test_login_rate_limited(client):
    for _ in range(10):
        client.post("/api/auth/login", json={"username": "", "password": "wrong"})
    res = client.post("/api/auth/login", json={"username": "", "password": "secret"})
    assert res.status_code == 429
