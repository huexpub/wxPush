"""应用 / 模板 / webhook 的 CRUD 与投递。"""

from __future__ import annotations

from conftest import make_app, make_hook, make_template


def test_app_crud(admin):
    app = make_app(admin)
    assert app["secret_hint"].startswith("super")
    assert "secret" not in app

    listed = admin.get("/api/apps").json()["items"]
    assert len(listed) == 1

    updated = admin.patch(f"/api/apps/{app['id']}", json={"name": "改名"}).json()
    assert updated["name"] == "改名"
    # 不传 secret 不能把原值清掉
    assert updated["secret_hint"] == app["secret_hint"]

    rotated = admin.patch(f"/api/apps/{app['id']}", json={"secret": "another-secret"}).json()
    assert rotated["secret_hint"] != app["secret_hint"]

    assert admin.delete(f"/api/apps/{app['id']}").status_code == 200
    assert admin.get("/api/apps").json()["items"] == []


def test_app_validation(admin):
    res = admin.post("/api/apps", json={"name": "", "corp_id": "x", "agent_id": "1", "secret": "s"})
    assert res.status_code == 422


def test_template_crud(admin):
    template = make_template(admin)
    assert template["msg_type"] == "text"
    assert template["variables"] == ["title", "content"]

    res = admin.patch(f"/api/templates/{template['id']}", json={"content": "{{ body }}"})
    assert res.json()["variables"] == ["body"]

    assert admin.delete(f"/api/templates/{template['id']}").status_code == 200


def test_template_rejects_invalid_json(admin):
    res = admin.post(
        "/api/templates",
        json={"name": "坏卡片", "msg_type": "textcard", "content": "{not json}"},
    )
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_template"


def test_template_preview(admin):
    res = admin.post(
        "/api/templates/preview",
        json={"msg_type": "markdown", "content": "**{{ t }}**", "data": {"t": "标题"}},
    )
    assert res.json()["rendered"] == "**标题**"


def test_hook_creation_and_key_reveal(admin):
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])
    assert hook["key"].startswith("wxp_")

    revealed = admin.get(f"/api/hooks/{hook['id']}/key").json()["key"]
    assert revealed == hook["key"]

    listed = admin.get("/api/hooks").json()["items"]
    assert listed[0]["app_name"] == "测试应用"
    assert "key" not in listed[0]


def test_hook_rotate_invalidates_old_key(admin, fake_client):
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])

    new_key = admin.post(f"/api/hooks/{hook['id']}/rotate").json()["key"]
    assert new_key != hook["key"]

    old = admin.post(f"/api/hook/{hook['key']}", json={"title": "a", "content": "b"})
    assert old.status_code == 404
    new = admin.post(f"/api/hook/{new_key}", json={"title": "a", "content": "b"})
    assert new.status_code == 200


def test_deliver_text(admin, fake_client):
    app = make_app(admin)
    template = make_template(admin, content="{{ title }} => {{ content }}")
    hook = make_hook(admin, app["id"], template["id"])

    res = admin.post(f"/api/hook/{hook['key']}", json={"title": "构建", "content": "成功"})
    assert res.status_code == 200, res.text
    assert res.json()["rendered"] == "构建 => 成功"

    call = fake_client.calls[-1]
    assert call["corp_id"] == "ww_test_corp"
    assert call["agent_id"] == "1000002"
    assert call["secret"] == "super-secret-value"
    assert call["msg_type"] == "text"
    assert call["touser"] == "zhangsan"


def test_deliver_plain_text_body(admin, fake_client):
    app = make_app(admin)
    template = make_template(admin, content=">>> {{ content }}")
    hook = make_hook(admin, app["id"], template["id"])

    res = admin.post(
        f"/api/hook/{hook['key']}",
        content="一段纯文本".encode(),
        headers={"Content-Type": "text/plain"},
    )
    assert res.status_code == 200
    assert fake_client.calls[-1]["content"].endswith("一段纯文本")


def test_deliver_overrides_touser(admin, fake_client):
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])
    admin.post(
        f"/api/hook/{hook['key']}", json={"title": "t", "content": "c", "touser": "lisi"}
    )
    assert fake_client.calls[-1]["touser"] == "lisi"
    assert "touser" not in admin.get("/api/messages").json()["items"][0]["payload"]


def test_deliver_header_key(admin, fake_client):
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])
    res = admin.post(
        "/api/hook",
        json={"title": "t", "content": "c"},
        headers={"X-Wxpush-Key": hook["key"]},
    )
    assert res.status_code == 200


def test_failure_is_recorded(admin, fake_client):
    fake_client.fail_with = (81013, "user & party & tag all invalid")
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])

    res = admin.post(f"/api/hook/{hook['key']}", json={"title": "t", "content": "c"})
    assert res.status_code == 502

    items = admin.get("/api/messages").json()["items"]
    assert items[0]["status"] == "failed"
    assert "81013" in items[0]["error"]
    assert "可见范围" in items[0]["error"]


def test_disabled_hook_rejected(admin, fake_client):
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])
    admin.patch(f"/api/hooks/{hook['id']}", json={"enabled": False})

    res = admin.post(f"/api/hook/{hook['key']}", json={"title": "t", "content": "c"})
    assert res.status_code == 403
    assert fake_client.calls == []


def test_bad_key(admin):
    assert admin.post("/api/hook/wxp_notexists", json={}).status_code == 404
    assert admin.post("/api/hook/nope", json={}).status_code == 404


def test_payload_too_large(admin, settings):
    object.__setattr__(settings, "max_payload_bytes", 32)
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])
    res = admin.post(f"/api/hook/{hook['key']}", json={"title": "x" * 100, "content": "c"})
    assert res.status_code == 413


def test_message_history_and_resend(admin, fake_client):
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])
    admin.post(f"/api/hook/{hook['key']}", json={"title": "第一次", "content": "c"})

    listing = admin.get("/api/messages").json()
    assert listing["total"] == 1
    message = listing["items"][0]
    assert message["payload"]["title"] == "第一次"

    res = admin.post(f"/api/messages/{message['id']}/resend")
    assert res.status_code == 200
    assert fake_client.calls[-1]["content"] == "第一次: c"
    assert admin.get("/api/messages").json()["total"] == 2


def test_message_filters(admin):
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])
    admin.post(f"/api/hook/{hook['key']}", json={"title": "成功", "content": "c"})
    admin.post(f"/api/hook/{hook['key']}", json={"content": "只有内容"})  # 缺 title 仍可发

    assert admin.get("/api/messages", params={"q": "成功"}).json()["total"] == 1
    assert admin.get("/api/messages", params={"status": "success"}).json()["total"] == 2
    assert admin.get("/api/messages", params={"status": "failed"}).json()["total"] == 0


def test_message_delete_and_clear(admin):
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])
    for i in range(3):
        admin.post(f"/api/hook/{hook['key']}", json={"title": str(i), "content": "c"})

    items = admin.get("/api/messages").json()["items"]
    admin.delete(f"/api/messages/{items[0]['id']}")
    assert admin.get("/api/messages").json()["total"] == 2

    res = admin.delete("/api/messages").json()
    assert res["deleted"] == 2
    assert admin.get("/api/messages").json()["total"] == 0


def test_stats(admin):
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])
    admin.post(f"/api/hook/{hook['key']}", json={"title": "t", "content": "c"})
    stats = admin.get("/api/stats").json()
    assert stats["apps"] == 1
    assert stats["templates"] == 1
    assert stats["hooks"] == 1
    assert stats["messages_24h"] == 1
    assert stats["recent"][0]["status"] == "success"


def test_app_test_endpoint(admin, fake_client):
    app = make_app(admin)
    res = admin.post(f"/api/apps/{app['id']}/test", json={"content": "hello"})
    assert res.status_code == 200
    assert fake_client.calls[-1]["content"] == "hello"


def test_deleting_app_cascades_hooks(admin):
    app = make_app(admin)
    template = make_template(admin)
    make_hook(admin, app["id"], template["id"])
    admin.delete(f"/api/apps/{app['id']}")
    assert admin.get("/api/hooks").json()["items"] == []


def test_history_survives_app_deletion(admin):
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])
    admin.post(f"/api/hook/{hook['key']}", json={"title": "t", "content": "c"})

    admin.delete(f"/api/apps/{app['id']}")
    items = admin.get("/api/messages").json()["items"]
    assert items[0]["app_name"] == "测试应用"
    assert items[0]["hook_id"] is None


def test_wecom_exception_recorded(admin, fake_client):
    from wxpush.wecom import WeComError

    fake_client.raise_error = WeComError("连接超时")
    app = make_app(admin)
    template = make_template(admin)
    hook = make_hook(admin, app["id"], template["id"])

    res = admin.post(f"/api/hook/{hook['key']}", json={"title": "t", "content": "c"})
    assert res.status_code == 502
    assert admin.get("/api/messages").json()["items"][0]["error"] == "连接超时"
