"""HTTP 层：只做参数校验 + 状态码映射，业务判定全在 ``service``。

接口一览：

    公开
    POST /api/hook/{key}              webhook 投递（JSON = 模板变量）
    GET  /api/healthz                 探活

    管理员（配了 WXPUSH_ADMIN_PASSWORD 才需要登录）
    POST   /api/auth/login
    POST   /api/auth/logout
    GET    /api/auth/session
    GET    /api/stats
    GET    /api/apps                  应用 CRUD
    POST   /api/apps
    PATCH  /api/apps/{id}
    DELETE /api/apps/{id}
    POST   /api/apps/{id}/test        发一条测试消息
    GET    /api/templates             模板 CRUD
    POST   /api/templates
    PATCH  /api/templates/{id}
    DELETE /api/templates/{id}
    POST   /api/templates/preview     用示例数据渲染
    GET    /api/hooks                 webhook CRUD
    POST   /api/hooks
    PATCH  /api/hooks/{id}
    DELETE /api/hooks/{id}
    GET    /api/hooks/{id}/key        查看明文 key
    POST   /api/hooks/{id}/rotate     轮换 key
    GET    /api/messages              历史
    GET    /api/messages/{id}
    DELETE /api/messages/{id}
    DELETE /api/messages              清空
    POST   /api/messages/{id}/resend

约定：错误统一是 ``{"error": "<code>", "message": "<中文说明>"}``。
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import auth
from .config import Settings
from .ratelimit import SlidingWindow
from .service import Service, ServiceError
from .wecom import MSG_TYPES, WeComError

router = APIRouter()


# ---------------------------------------------------------------- 请求体


class LoginBody(BaseModel):
    username: str = ""
    password: str = Field(max_length=512)


class AppBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    corp_id: str = Field(min_length=1, max_length=100)
    agent_id: str = Field(min_length=1, max_length=40)
    secret: str = Field(min_length=1, max_length=200)
    default_touser: str = ""


class AppPatch(BaseModel):
    name: str | None = None
    corp_id: str | None = None
    agent_id: str | None = None
    secret: str | None = None
    default_touser: str | None = None
    enabled: bool | None = None


class TemplateBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    msg_type: str = "text"
    content: str = Field(min_length=1)


class TemplatePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    msg_type: str | None = None
    content: str | None = None


class TemplatePreviewBody(BaseModel):
    msg_type: str
    content: str
    data: dict[str, Any] = Field(default_factory=dict)


class HookBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    app_id: str
    template_id: str


class HookPatch(BaseModel):
    name: str | None = None
    app_id: str | None = None
    template_id: str | None = None
    enabled: bool | None = None


class TestAppBody(BaseModel):
    content: str = "WXPUSH 测试消息：应用配置可用。"


# ---------------------------------------------------------------- 依赖


def get_service(request: Request) -> Service:
    return request.app.state.service


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


admin = Depends(auth.require_admin)


# ---------------------------------------------------------------- 错误


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            {"error": exc.code, "message": exc.message}, status_code=exc.status
        )

    @app.exception_handler(WeComError)
    async def _wecom_error(_: Request, exc: WeComError) -> JSONResponse:
        return JSONResponse(
            {"error": "wecom_error", "message": str(exc), "detail": exc.detail},
            status_code=502,
        )


# ---------------------------------------------------------------- 登录


@router.post("/auth/login")
def login(
    body: LoginBody,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    limiter: SlidingWindow = request.app.state.limiter
    ip = _client_ip(request)
    if not limiter.hit(f"login:{ip}", 10):
        raise ServiceError("too_many_attempts", "尝试过于频繁，请一分钟后再试", 429)
    if not settings.gate_enabled:
        raise ServiceError("gate_disabled", "服务未设置管理员密码，无需登录", 400)
    if not auth.check_password(settings, body.username, body.password):
        raise ServiceError("invalid_credentials", "用户名或密码错误", 401)

    subject = settings.admin_user or "admin"
    token = auth.issue_session(
        request.app.state.secret, subject, settings.session_ttl_hours * 3600
    )
    response = JSONResponse({"ok": True, "subject": subject})
    auth.set_session_cookie(response, settings, token)
    return response


@router.post("/auth/logout")
def logout(request: Request, settings: Settings = Depends(get_settings)) -> JSONResponse:
    response = JSONResponse({"ok": True})
    auth.clear_session_cookie(response, settings)
    return response


@router.get("/auth/session")
def session_info(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    subject = auth.current_subject(request)
    return {
        "gate": settings.gate_enabled,
        "authenticated": bool(subject) or not settings.gate_enabled,
        "subject": subject,
        "user": settings.admin_user,
    }


# ---------------------------------------------------------------- 统计


@router.get("/stats")
def stats(service: Service = Depends(get_service), _: str = admin) -> dict[str, Any]:
    return service.stats()


# ---------------------------------------------------------------- 应用


@router.get("/apps")
def list_apps(service: Service = Depends(get_service), _: str = admin) -> dict[str, Any]:
    return {"items": service.list_apps()}


@router.post("/apps")
def create_app(
    body: AppBody, service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    return service.create_app(**body.model_dump())


@router.patch("/apps/{app_id}")
def patch_app(
    app_id: str,
    body: AppPatch,
    service: Service = Depends(get_service),
    _: str = admin,
) -> dict[str, Any]:
    return service.update_app(app_id, **body.model_dump(exclude_none=True))


@router.delete("/apps/{app_id}")
def delete_app(
    app_id: str, service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    service.delete_app(app_id)
    return {"ok": True}


@router.post("/apps/{app_id}/test")
def test_app(
    app_id: str,
    body: TestAppBody,
    service: Service = Depends(get_service),
    _: str = admin,
) -> dict[str, Any]:
    """用该应用的凭据给自己发一条纯文本，验证三要素是否正确。"""
    from .db import session

    with session(service.settings.db_path) as conn:
        row = conn.execute("SELECT * FROM apps WHERE id = ?", (app_id,)).fetchone()
    if not row:
        raise ServiceError("app_not_found", "应用不存在", 404)
    secret = service.cipher.decrypt(row["secret_enc"])
    result = service.client.send(
        corp_id=row["corp_id"],
        agent_id=row["agent_id"],
        secret=secret,
        msg_type="text",
        content=body.content,
        touser=row["default_touser"] or "@all",
    )
    if not result.ok:
        raise ServiceError(
            "send_failed", f"企业微信错误 {result.errcode}：{result.errmsg}", 502
        )
    return {"ok": True, "response": result.response}


# ---------------------------------------------------------------- 模板


@router.get("/templates")
def list_templates(
    service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    return {"items": service.list_templates(), "msg_types": MSG_TYPES}


@router.post("/templates")
def create_template(
    body: TemplateBody, service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    return service.create_template(**body.model_dump())


@router.patch("/templates/{template_id}")
def patch_template(
    template_id: str,
    body: TemplatePatch,
    service: Service = Depends(get_service),
    _: str = admin,
) -> dict[str, Any]:
    return service.update_template(template_id, **body.model_dump(exclude_none=True))


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: str, service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    service.delete_template(template_id)
    return {"ok": True}


@router.post("/templates/preview")
def preview_template(
    body: TemplatePreviewBody,
    service: Service = Depends(get_service),
    _: str = admin,
) -> dict[str, Any]:
    from .templating import TemplateError, placeholders, render_content

    try:
        rendered = render_content(body.msg_type, body.content, body.data)
    except TemplateError as exc:
        raise ServiceError("invalid_template", str(exc)) from exc
    return {
        "rendered": rendered,
        "variables": placeholders(body.content),
        "is_json": body.msg_type in {"textcard", "news"},
    }


# ---------------------------------------------------------------- webhook 管理


@router.get("/hooks")
def list_hooks(service: Service = Depends(get_service), _: str = admin) -> dict[str, Any]:
    return {"items": service.list_hooks()}


@router.post("/hooks")
def create_hook(
    body: HookBody, service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    return service.create_hook(**body.model_dump())


@router.patch("/hooks/{hook_id}")
def patch_hook(
    hook_id: str,
    body: HookPatch,
    service: Service = Depends(get_service),
    _: str = admin,
) -> dict[str, Any]:
    return service.update_hook(hook_id, **body.model_dump(exclude_none=True))


@router.delete("/hooks/{hook_id}")
def delete_hook(
    hook_id: str, service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    service.delete_hook(hook_id)
    return {"ok": True}


@router.get("/hooks/{hook_id}/key")
def reveal_hook(
    hook_id: str, service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    return {"key": service.reveal_key(hook_id)}


@router.post("/hooks/{hook_id}/rotate")
def rotate_hook(
    hook_id: str, service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    return service.rotate_hook(hook_id)


# ---------------------------------------------------------------- 历史


@router.get("/messages")
def list_messages(
    limit: int = 50,
    offset: int = 0,
    status: str = "",
    app_id: str = "",
    hook_id: str = "",
    q: str = "",
    service: Service = Depends(get_service),
    _: str = admin,
) -> dict[str, Any]:
    return service.list_messages(
        limit=max(1, min(limit, 200)),
        offset=max(0, offset),
        status=status,
        app_id=app_id,
        hook_id=hook_id,
        query=q,
    )


@router.get("/messages/{message_id}")
def get_message(
    message_id: str, service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    return service.get_message(message_id)


@router.delete("/messages/{message_id}")
def delete_message(
    message_id: str, service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    service.delete_message(message_id)
    return {"ok": True}


@router.delete("/messages")
def clear_messages(service: Service = Depends(get_service), _: str = admin) -> dict[str, Any]:
    return {"ok": True, "deleted": service.clear_messages()}


@router.post("/messages/{message_id}/resend")
def resend_message(
    message_id: str, service: Service = Depends(get_service), _: str = admin
) -> dict[str, Any]:
    return service.resend(message_id)


# ---------------------------------------------------------------- 公开 webhook


@router.post("/hook/{key}")
async def hook(key: str, request: Request, service: Service = Depends(get_service)) -> dict[str, Any]:
    return await _deliver(service, request, key)


@router.post("/hook")
async def hook_body_key(request: Request, service: Service = Depends(get_service)) -> dict[str, Any]:
    """key 也可以放在 header / query 里 —— 有些平台的 URL 模板不方便塞路径。"""
    key = (
        request.headers.get("x-wxpush-key")
        or request.query_params.get("key")
        or ""
    )
    return await _deliver(service, request, key)


async def _deliver(service: Service, request: Request, key: str) -> dict[str, Any]:
    settings = service.settings
    limiter: SlidingWindow = request.app.state.limiter
    fingerprint = key[-8:] if key else "none"
    if not limiter.hit(f"hook:{fingerprint}", settings.rate_limit_per_minute):
        raise ServiceError("rate_limited", "调用过于频繁，请稍后再试", 429)

    raw = await request.body()
    if len(raw) > settings.max_payload_bytes:
        raise ServiceError("payload_too_large", "请求体过大", 413)

    content_type = request.headers.get("content-type", "")
    data: dict[str, Any] = {}
    touser = ""
    try:
        if "application/x-www-form-urlencoded" in content_type:
            # 表单要在「非空就当纯文本」之前判断，否则会被当成一段原文
            form = await request.form()
            data = {k: str(v) for k, v in form.items()}
            touser = str(data.pop("touser", "") or "")
        elif raw.strip():
            if "application/json" in content_type or raw.lstrip().startswith(b"{"):
                parsed = json.loads(raw.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise ServiceError("invalid_payload", "请求体必须是 JSON 对象")
                data = {k: v for k, v in parsed.items() if not k.startswith("_")}
                touser = str(data.pop("touser", "") or "")
            else:
                # 纯文本：整段当 content，模板里写 {{ content }} 即可
                data = {"content": raw.decode("utf-8", "replace")}
    except UnicodeDecodeError as exc:
        raise ServiceError("invalid_encoding", "请求体不是 UTF-8 文本") from exc
    except json.JSONDecodeError as exc:
        raise ServiceError("invalid_json", f"JSON 解析失败：{exc.msg}") from exc

    data.setdefault("time", time.strftime("%Y-%m-%d %H:%M:%S"))
    hook = service.resolve_hook(key)
    result = service.deliver(hook, data, touser=touser, ip=_client_ip(request))
    return {"ok": True, **result}


@router.get("/healthz")
def healthz(service: Service = Depends(get_service)) -> dict[str, Any]:
    from .db import session

    with session(service.settings.db_path) as conn:
        conn.execute("SELECT 1").fetchone()
    return {"ok": True, "version": _version()}


def _version() -> str:
    from . import __version__

    return __version__


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else ""


@router.get("/healthz.txt", include_in_schema=False)
def healthz_text() -> Response:
    return Response("ok")
