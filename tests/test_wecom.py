"""企业微信客户端：token 缓存、错误码重试、消息体组装。

用 httpx 的 MockTransport 不行 —— 客户端是用 urllib 写的（零依赖）。
这里直接把 ``_request`` 换成脚本化的假实现，验证的是「怎么调接口」。
"""

from __future__ import annotations

import json

import pytest

from wxpush.wecom import MSG_TYPES, WeComClient, WeComError, _TokenCache


@pytest.fixture(autouse=True)
def clean_tokens():
    from wxpush import wecom

    wecom.TOKENS.clear()
    yield
    wecom.TOKENS.clear()


class ScriptedClient(WeComClient):
    """按顺序回放响应。"""

    def __init__(self, responses):
        super().__init__("https://example.invalid", timeout=1)
        self.responses = list(responses)
        self.requests: list[tuple[str, str, dict, object]] = []

    def _request(self, method, path, query, body=None):
        self.requests.append((method, path, query, body))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def token_ok(token: str = "T") -> dict:
    return {"errcode": 0, "access_token": token, "expires_in": 7200}


def send_ok() -> dict:
    return {"errcode": 0, "errmsg": "ok"}


def test_send_text_builds_body():
    client = ScriptedClient([token_ok(), send_ok()])
    result = client.send(
        corp_id="ww1",
        agent_id="1000002",
        secret="s",
        msg_type="text",
        content="hello",
        touser="zhangsan",
    )
    assert result.ok
    method, path, query, body = client.requests[1]
    assert method == "POST"
    assert path == "/cgi-bin/message/send"
    assert query["access_token"] == "T"
    assert body["msgtype"] == "text"
    assert body["text"] == {"content": "hello"}
    assert body["agentid"] == 1000002
    assert body["touser"] == "zhangsan"


def test_touser_defaults_to_all():
    client = ScriptedClient([token_ok(), send_ok()])
    client.send(corp_id="c", agent_id="1", secret="s", msg_type="text", content="x")
    assert client.requests[1][3]["touser"] == "@all"


def test_textcard_body_is_parsed():
    client = ScriptedClient([token_ok(), send_ok()])
    content = json.dumps({"title": "t", "description": "d", "url": "https://x"})
    client.send(corp_id="c", agent_id="1", secret="s", msg_type="textcard", content=content)
    assert client.requests[1][3]["textcard"]["title"] == "t"


def test_token_is_cached_between_sends():
    client = ScriptedClient([token_ok(), send_ok(), send_ok()])
    for _ in range(2):
        client.send(corp_id="c", agent_id="1", secret="s", msg_type="text", content="x")
    # 两次发送只取了一次 token
    assert [r[1] for r in client.requests] == [
        "/cgi-bin/gettoken",
        "/cgi-bin/message/send",
        "/cgi-bin/message/send",
    ]


def test_stale_token_refetched():
    client = ScriptedClient([
        token_ok("OLD"),
        {"errcode": 42001, "errmsg": "access_token expired"},
        token_ok("NEW"),
        send_ok(),
    ])
    result = client.send(corp_id="c", agent_id="1", secret="s", msg_type="text", content="x")
    assert result.ok
    send_calls = [r for r in client.requests if r[1] == "/cgi-bin/message/send"]
    assert [c[2]["access_token"] for c in send_calls] == ["OLD", "NEW"]


def test_gettoken_failure():
    client = ScriptedClient([{"errcode": 40013, "errmsg": "invalid corpid"}])
    with pytest.raises(WeComError) as excinfo:
        client.send(corp_id="c", agent_id="1", secret="s", msg_type="text", content="x")
    assert excinfo.value.errcode == 40013
    assert "invalid corpid" in str(excinfo.value)


def test_send_failure_is_returned_not_raised():
    client = ScriptedClient([token_ok(), {"errcode": 81013, "errmsg": "invalid user"}])
    result = client.send(corp_id="c", agent_id="1", secret="s", msg_type="text", content="x")
    assert not result.ok
    assert result.errcode == 81013


def test_unknown_msg_type_rejected():
    client = ScriptedClient([])
    with pytest.raises(WeComError):
        client.send(corp_id="c", agent_id="1", secret="s", msg_type="video", content="x")


def test_all_msg_types_supported():
    assert set(MSG_TYPES) == {"text", "markdown", "textcard", "news"}


def test_cache_expires_five_minutes_early():
    import time

    cache = _TokenCache()
    cache.put(("c", "1"), "tok", 400)
    item = cache.get(("c", "1"))
    assert item is not None
    # 400 - 300 = 100 秒，而不是完整的 400 秒
    assert 90 <= item[1] - time.time() <= 110


def test_cache_floor_on_short_ttl():
    cache = _TokenCache()
    cache.put(("c", "1"), "tok", 30)
    # 企业微信罕见地给了很短的有效期时，至少缓存 60 秒
    assert cache.get(("c", "1")) is not None
    cache.drop(("c", "1"))
    assert cache.get(("c", "1")) is None


def test_cache_hit():
    cache = _TokenCache()
    cache.put(("c", "1"), "tok", 7200)
    assert cache.get(("c", "1")) == ("tok", cache.get(("c", "1"))[1])
    cache.drop(("c", "1"))
    assert cache.get(("c", "1")) is None
