"""应用装配。

FastAPI + 单进程内限速 + SQLite。前端是 Vite 构建产物（``wxpush/static``），
由 ``web.py`` 直接吐出去 —— 部署时只有一个 Python 进程，不需要 nginx。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from . import __version__
from .api import register_error_handlers, router
from .config import Settings
from .crypto import Cipher, load_key
from .db import init_db
from .ratelimit import SlidingWindow
from .service import Service
from .web import build_web_router

log = logging.getLogger("wxpush")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_dirs()
    init_db(settings.db_path)
    key = load_key(settings.key_path, settings.encryption_key)
    service = Service(settings, Cipher(key))

    app = FastAPI(
        title="WXPUSH",
        version=__version__,
        description="企业微信应用消息推送后台",
        docs_url=f"{settings.api_prefix}/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=_make_lifespan(settings, service),
    )
    app.state.settings = settings
    app.state.service = service
    app.state.secret = key
    app.state.limiter = SlidingWindow()

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    register_error_handlers(app)
    app.include_router(router, prefix=settings.api_prefix)
    app.include_router(build_web_router(settings))
    return app


def _make_lifespan(settings: Settings, service: Service):
    """内置清理任务放在 lifespan 里：不依赖外部 cron，也不碰已弃用的 on_event。

    启动时先清一次（进程可能已经停了很久），之后按 ``purge_interval_seconds``
    周期执行；退出时取消后台任务。
    """

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        _log_startup(settings)
        task = asyncio.create_task(_purge_loop(settings, service))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return lifespan


async def _purge_loop(settings: Settings, service: Service) -> None:
    interval = max(60, settings.purge_interval_seconds)
    while True:
        try:
            removed = await asyncio.to_thread(service.purge_messages)
            if removed:
                log.info("清理了 %s 条超过 %s 天的消息", removed, settings.message_retention_days)
        except asyncio.CancelledError:
            raise
        except Exception:  # 清理失败不能影响服务
            log.exception("清理历史失败")
        await asyncio.sleep(interval)


def _log_startup(settings: Settings) -> None:
    log.info("WXPUSH %s", __version__)
    log.info("数据目录：%s", settings.data_dir)
    log.info("挂载前缀：%s", settings.prefix or "/")
    if not settings.gate_enabled:
        log.warning("未设置 WXPUSH_ADMIN_PASSWORD —— 任何人都能管理，公网部署请务必配置")
