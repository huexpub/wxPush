"""页面路由：Vue 构建产物 + SPA 回退。

前端是 Vite 单页应用，构建产物复制到 ``wxpush/static``：

    wxpush/static/index.html
    wxpush/static/assets/index-<hash>.js|css

路由策略：
  * 真实文件存在就返回文件（带长期缓存头，文件名里有 hash）；
  * ``/api/...`` 以外的一切路径回 ``index.html``（前端路由接管）；
  * 构建产物不存在时给一段说明页 —— 开发时只跑后端也不会一脸 404。
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.responses import Response

from .config import DIST_DIR

_MEDIA_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
    ".png": "image/png",
}

_FALLBACK_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>WXPUSH</title>
<style>body{font-family:system-ui,sans-serif;background:#0a0e15;color:#e6edf3;
display:grid;place-items:center;height:100vh;margin:0}main{max-width:520px;padding:32px}
code{background:#161c26;padding:2px 6px;border:1px solid #232b38}</style></head>
<body><main><h1>WXPUSH 后端已启动</h1>
<p>前端还没有构建。两种做法：</p>
<ol><li>开发：<code>cd web &amp;&amp; npm install &amp;&amp; npm run dev</code>，打开 Vite 的地址。</li>
<li>部署：<code>npm run build</code> 会自动把产物复制到 <code>wxpush/static</code>。</li></ol>
<p>API 文档：<a href="__DOCS__" style="color:#3b82f6">__DOCS__</a></p></main></body></html>"""


def _media_type(path: Path) -> str:
    # Windows 注册表里 .js 的 MIME 常被改成 text/plain，ES module 会被整块拒绝
    return (
        _MEDIA_TYPES.get(path.suffix.lower())
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


def _index_html(settings) -> str:
    index = DIST_DIR / "index.html"
    if not index.is_file():
        docs = f"{settings.api_prefix}/docs"
        return _FALLBACK_HTML.replace("__DOCS__", docs)
    html = index.read_text(encoding="utf-8")
    base = settings.prefix
    boot = (
        f"<script>window.__WXPUSH_BASE__={json.dumps(base)};"
        f"window.__WXPUSH_API__={json.dumps(settings.api_prefix)};"
        f"window.__WXPUSH_GATE__={json.dumps(settings.gate_enabled)};"
        f"window.__WXPUSH_FOOTER__={json.dumps(settings.footer)};</script>"
    )
    # 前缀与运行时配置必须在模块脚本之前注入
    if "</head>" in html:
        return html.replace("</head>", f"{boot}\n</head>", 1)
    return boot + html


def build_web_router(settings) -> APIRouter:
    router = APIRouter()
    prefix = settings.prefix
    root = DIST_DIR.resolve()

    @router.get(f"{prefix}/" if prefix else "/", include_in_schema=False)
    def index() -> HTMLResponse:
        return HTMLResponse(_index_html(settings), headers={"Cache-Control": "no-cache"})

    @router.get(f"{prefix}/static/{{path:path}}", include_in_schema=False)
    def static_asset(path: str) -> Response:
        return _serve_asset(path)

    @router.get(f"{prefix}/assets/{{path:path}}", include_in_schema=False)
    def hashed_asset(path: str) -> Response:
        # 路由已经吃掉了 /assets 前缀，这里要补回去
        return _serve_asset(f"assets/{path}")

    def _serve_asset(relative: str) -> Response:
        target = (DIST_DIR / relative).resolve()
        if root not in target.parents or not target.is_file():
            return JSONResponse({"error": "not_found"}, status_code=404)
        # assets 文件名带 hash，可以长缓存；其它静态文件短缓存
        cache = (
            "public, max-age=31536000, immutable"
            if "/assets/" in target.as_posix() or relative.startswith("assets/")
            else "no-cache"
        )
        return FileResponse(target, media_type=_media_type(target), headers={"Cache-Control": cache})

    @router.get(f"{prefix}/favicon.svg", include_in_schema=False)
    def favicon() -> Response:
        target = DIST_DIR / "favicon.svg"
        if not target.is_file():
            return Response(status_code=204)
        return FileResponse(target, media_type="image/svg+xml")

    @router.get(f"{prefix}/{{path:path}}", include_in_schema=False)
    def spa(path: str) -> HTMLResponse:
        # API 前缀下的未知路径应该 404，而不是回 index.html
        api = settings.api_prefix.lstrip("/")
        if path == api or path.startswith(f"{api}/"):
            return JSONResponse({"error": "not_found"}, status_code=404)
        target = (DIST_DIR / path).resolve()
        if root in target.parents and target.is_file():
            return FileResponse(target, media_type=_media_type(target))
        return HTMLResponse(_index_html(settings), headers={"Cache-Control": "no-cache"})

    return router
