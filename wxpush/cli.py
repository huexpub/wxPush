"""命令行入口。

    python -m wxpush serve            # 起服务
    python -m wxpush purge            # 清理过期历史
    python -m wxpush info             # 配置与统计
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace

from .app import create_app
from .config import Settings
from .crypto import Cipher, load_key
from .db import init_db, session
from .service import Service


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = Settings.from_env()
    if args.host:
        settings = replace(settings, host=args.host)
    if args.port:
        settings = replace(settings, port=args.port)
    if args.data_dir:
        settings = replace(settings, data_dir=args.data_dir)
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=args.log_level)
    return 0


def cmd_purge(_: argparse.Namespace) -> int:
    settings = Settings.from_env()
    settings.ensure_dirs()
    init_db(settings.db_path)
    service = Service(settings, Cipher(load_key(settings.key_path, settings.encryption_key)))
    print(json.dumps({"removed": service.purge_messages()}, ensure_ascii=False))
    return 0


def cmd_info(_: argparse.Namespace) -> int:
    settings = Settings.from_env()
    settings.ensure_dirs()
    init_db(settings.db_path)
    with session(settings.db_path) as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in ("apps", "templates", "hooks", "messages")
        }
    info = {
        "data_dir": str(settings.data_dir),
        "db": str(settings.db_path),
        "prefix": settings.prefix or "/",
        "gate": settings.gate_enabled,
        "counts": counts,
        "retention_days": settings.message_retention_days,
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wxpush", description="企业微信应用推送后台")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="启动 HTTP 服务")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--data-dir")
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(func=cmd_serve)

    purge = sub.add_parser("purge", help="清理超过保留期的消息历史")
    purge.set_defaults(func=cmd_purge)

    info = sub.add_parser("info", help="查看配置与统计")
    info.set_defaults(func=cmd_info)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
