"""测试装配：真实 SQLite + 假的企业微信服务器（注入的发送器）。

不起网络请求：``WeComClient`` 被替换成记录调用的假实现，这样测试断言的是
「我们发出了什么」，而不是企业微信怎么答。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxpush.app import create_app
from wxpush.config import Settings
from wxpush.wecom import SendResult


class FakeClient:
    """替身：记录每次 send 的参数，可配置返回成功/失败。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_with: tuple[int, str] | None = None
        self.raise_error: Exception | None = None

    def send(self, **kwargs):
        if self.raise_error:
            raise self.raise_error
        self.calls.append(kwargs)
        if self.fail_with:
            errcode, errmsg = self.fail_with
            return SendResult(ok=False, response=f'{{"errcode":{errcode}}}', errcode=errcode, errmsg=errmsg)
        return SendResult(ok=True, response='{"errcode":0,"errmsg":"ok"}', errcode=0, errmsg="ok")

    def token(self, *args, **kwargs):  # pragma: no cover - 替身不需要
        return "token"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", admin_password="secret", admin_user="")


@pytest.fixture
def app(settings: Settings):
    application = create_app(settings)
    application.state.service.client = FakeClient()
    application.state.service.settings = settings
    return application


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fake_client(app) -> FakeClient:
    return app.state.service.client


@pytest.fixture
def service(app):
    return app.state.service


@pytest.fixture
def admin(client):
    """已登录的 client；同时返回 app 便于直接调 service。"""
    res = client.post("/api/auth/login", json={"username": "", "password": "secret"})
    assert res.status_code == 200, res.text
    return client


def make_app(client, name: str = "测试应用") -> dict:
    res = client.post(
        "/api/apps",
        json={
            "name": name,
            "corp_id": "ww_test_corp",
            "agent_id": "1000002",
            "secret": "super-secret-value",
            "default_touser": "zhangsan",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def make_template(client, msg_type: str = "text", content: str = "{{ title }}: {{ content }}") -> dict:
    res = client.post(
        "/api/templates",
        json={"name": "测试模板", "msg_type": msg_type, "content": content},
    )
    assert res.status_code == 200, res.text
    return res.json()


def make_hook(client, app_id: str, template_id: str) -> dict:
    res = client.post(
        "/api/hooks",
        json={"name": "测试 webhook", "app_id": app_id, "template_id": template_id},
    )
    assert res.status_code == 200, res.text
    return res.json()
