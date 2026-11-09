"""企业微信「自建应用」消息发送。

接口（全部是 GET/POST + JSON，没有加密信封 —— 那是「群机器人 webhook」和
「第三方回调」才有的东西；自建应用走 corpsecret 换 token 即可）：

    GET  /cgi-bin/gettoken?corpid=&corpsecret=      -> access_token
    POST /cgi-bin/message/send?access_token=        -> 发送应用消息

token 有效期 7200 秒，且**每个应用每 7200 秒只能取有限次**，所以必须缓存。
缓存放在进程内：单进程部署，重启重取一次可以接受。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

#: 支持的 msgtype（够覆盖通知场景；需要更多再加）
MSG_TYPES = ("text", "markdown", "textcard", "news")

MSG_TYPE_LABELS = {
    "text": "纯文本",
    "markdown": "Markdown",
    "textcard": "文本卡片",
    "news": "图文消息",
}

DEFAULT_CONTENT = {
    "text": "{{ title }}\n{{ content }}",
    "markdown": "**{{ title }}**\n\n{{ content }}",
    "textcard": json.dumps(
        {
            "title": "{{ title }}",
            "description": "{{ content }}",
            "url": "{{ url }}",
            "btntxt": "详情",
        },
        ensure_ascii=False,
        indent=2,
    ),
    "news": json.dumps(
        {
            "articles": [
                {"title": "{{ title }}", "description": "{{ content }}", "url": "{{ url }}"}
            ]
        },
        ensure_ascii=False,
        indent=2,
    ),
}


class WeComError(RuntimeError):
    def __init__(self, message: str, errcode: int | None = None, detail: str = "") -> None:
        super().__init__(message)
        self.errcode = errcode
        self.detail = detail


@dataclass(slots=True)
class SendResult:
    ok: bool
    response: str
    errcode: int | None = None
    errmsg: str = ""


class _TokenCache:
    """corp_id + agent 维度的 token 缓存，带提前 5 分钟过期。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[tuple[str, str], tuple[str, float]] = {}

    def get(self, key: tuple[str, str]) -> tuple[str, float] | None:
        with self._lock:
            item = self._items.get(key)
            if item and item[1] > time.time():
                return item
            return None

    def put(self, key: tuple[str, str], token: str, expires_in: int) -> None:
        ttl = max(60, expires_in - 300)
        with self._lock:
            self._items[key] = (token, time.time() + ttl)

    def drop(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._items.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


TOKENS = _TokenCache()


class WeComClient:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------ 底层请求

    def _request(self, method: str, path: str, query: dict[str, str], body: Any = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            raise WeComError(f"企业微信返回 HTTP {exc.code}", detail=raw[:500]) from exc
        except urllib.error.URLError as exc:
            raise WeComError(f"连接企业微信失败：{exc.reason}") from exc
        except TimeoutError as exc:
            raise WeComError("连接企业微信超时") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WeComError("企业微信返回了非 JSON 内容", detail=raw[:500]) from exc

    # ------------------------------------------------------------ token

    def token(self, corp_id: str, agent_id: str, secret: str, force: bool = False) -> str:
        key = (corp_id, agent_id)
        if not force:
            cached = TOKENS.get(key)
            if cached:
                return cached[0]
        payload = self._request(
            "GET",
            "/cgi-bin/gettoken",
            {"corpid": corp_id, "corpsecret": secret},
        )
        errcode = int(payload.get("errcode", 0) or 0)
        if errcode != 0:
            raise WeComError(
                f"获取 access_token 失败：{payload.get('errmsg', '未知错误')}",
                errcode=errcode,
                detail=json.dumps(payload, ensure_ascii=False)[:500],
            )
        token = payload.get("access_token") or ""
        if not token:
            raise WeComError("企业微信没有返回 access_token", detail=json.dumps(payload, ensure_ascii=False))
        TOKENS.put(key, token, int(payload.get("expires_in", 7200) or 7200))
        return token

    # ------------------------------------------------------------ 发送

    def send(
        self,
        *,
        corp_id: str,
        agent_id: str,
        secret: str,
        msg_type: str,
        content: str,
        touser: str = "",
        toparty: str = "",
        totag: str = "",
    ) -> SendResult:
        if msg_type not in MSG_TYPES:
            raise WeComError(f"不支持的消息类型：{msg_type}")

        body: dict[str, Any] = {
            "touser": touser or "@all",
            "msgtype": msg_type,
            "agentid": int(agent_id) if agent_id.isdigit() else agent_id,
            "safe": 0,
        }
        if toparty:
            body["toparty"] = toparty
        if totag:
            body["totag"] = totag

        if msg_type in {"text", "markdown"}:
            body[msg_type] = {"content": content}
        else:
            body[msg_type] = json.loads(content)

        # token 可能被提前吊销（改了 secret / 后台刷新），40014/42001 时重取一次
        for attempt in range(2):
            token = self.token(corp_id, agent_id, secret, force=attempt > 0)
            payload = self._request(
                "POST", "/cgi-bin/message/send", {"access_token": token}, body
            )
            errcode = int(payload.get("errcode", 0) or 0)
            errmsg = str(payload.get("errmsg", ""))
            if errcode in (40014, 42001) and attempt == 0:
                TOKENS.drop((corp_id, agent_id))
                continue
            return SendResult(
                ok=errcode == 0,
                response=json.dumps(payload, ensure_ascii=False),
                errcode=errcode,
                errmsg=errmsg,
            )
        raise WeComError("access_token 反复失效", detail=json.dumps(payload, ensure_ascii=False))
