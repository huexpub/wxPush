"""管理员登录。

这个后台只有一个管理员，所以不需要用户表：

  * 密码来自 ``WXPUSH_ADMIN_PASSWORD``；配了 ``WXPUSH_ADMIN_USER`` 就要求两项；
  * 登录态是 HMAC 签名 cookie，密钥复用 ``data/secret.key``（与加密同一份）；
  * 密码本身就是明文配置，比较时用 ``hmac.compare_digest`` 防时序；
  * 暴力破解由 ``ratelimit`` 的每 IP 上限挡住。

webhook 接口**不走这里**：它用各自独立的 ``wxp_`` key。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from fastapi import HTTPException, Request

from .config import Settings

SESSION_COOKIE = "wxpush_session"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def sign(secret: bytes, payload: str) -> str:
    return _b64(hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).digest())


def issue_session(secret: bytes, subject: str, ttl_seconds: int) -> str:
    expires = int(time.time()) + ttl_seconds
    token = _b64(subject.encode("utf-8"))
    return f"{expires}.{token}.{sign(secret, f'session:{expires}.{subject}')}"


def session_subject(secret: bytes, raw: str | None) -> str | None:
    if not raw:
        return None
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    expires_raw, token, mac = parts
    try:
        expires = int(expires_raw)
    except ValueError:
        return None
    if expires < int(time.time()):
        return None
    try:
        subject = _unb64(token).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    expected = sign(secret, f"session:{expires}.{subject}")
    if not hmac.compare_digest(expected, mac):
        return None
    return subject


def check_password(settings: Settings, username: str, password: str) -> bool:
    expected = settings.admin_password
    if not expected:
        return False
    if settings.admin_user and not hmac.compare_digest(
        settings.admin_user.lower().encode("utf-8"), username.strip().lower().encode("utf-8")
    ):
        return False
    return hmac.compare_digest(expected.encode("utf-8"), password.encode("utf-8"))


def current_subject(request: Request) -> str | None:
    secret: bytes = request.app.state.secret
    return session_subject(secret, request.cookies.get(SESSION_COOKIE))


def require_admin(request: Request) -> str:
    """依赖：没配密码 = 不设闸门（本地/内网）；配了就要求有效会话。"""
    settings: Settings = request.app.state.settings
    if not settings.gate_enabled:
        return "anonymous"
    subject = current_subject(request)
    if not subject:
        raise HTTPException(status_code=401, detail="需要登录")
    return subject


def set_session_cookie(response, settings: Settings, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.on_https,
        path=settings.prefix or "/",
    )


def clear_session_cookie(response, settings: Settings) -> None:
    response.delete_cookie(SESSION_COOKIE, path=settings.prefix or "/")
