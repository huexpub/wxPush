"""运行配置。

全部来自环境变量（前缀 ``WXPUSH_``），不读配置文件：部署时就是
``docker compose up -d``，配置项越少越好。

``Settings`` 是 frozen dataclass —— 进程内只有一份，测试时直接构造新的。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PREFIX = "WXPUSH_"

#: 前端构建产物（Vite ``dist``）复制到这里；开发时目录可能是空的。
STATIC_DIR = Path(__file__).resolve().parent / "static"
DIST_DIR = STATIC_DIR


def _env(name: str) -> str | None:
    value = os.environ.get(PREFIX + name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:  # 配置写错要立刻炸，别静默回退
        raise ValueError(f"环境变量 {PREFIX}{name} 需要整数，当前为 {raw!r}") from exc


def _bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _normalize_prefix(value: str) -> str:
    return value.strip().strip("/")


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8000

    #: 对外域名，用于页面展示 webhook 地址（留空则前端用当前 origin）
    base_url: str = ""
    #: 挂载前缀。留空 = 根；填 ``wxpush`` = 整个服务住在 /wxpush 下
    path_prefix: str = ""

    #: 管理员闸门：设了密码才需要登录。公网部署必须设。
    admin_user: str = ""
    admin_password: str = ""
    #: 登录态有效期（小时）
    session_ttl_hours: int = 24 * 7
    #: cookie 是否只走 HTTPS；默认按 base_url 自动判断
    cookie_secure: bool = False

    #: 企业微信 API 根地址（测试时可指向 mock）
    wecom_base_url: str = "https://qyapi.weixin.qq.com"
    wecom_timeout_seconds: float = 15.0

    #: webhook 的限速（每个 key 每分钟）
    rate_limit_per_minute: int = 120
    #: 单次 webhook 请求体上限（字节）
    max_payload_bytes: int = 64 * 1024
    #: 消息历史保留天数；0 = 永久保留
    message_retention_days: int = 180
    #: 内置清理任务的间隔（秒）；默认一天
    purge_interval_seconds: int = 24 * 3600

    #: 加密密钥（base64 的 32 字节）。留空 = 使用 data/secret.key 自动生成
    encryption_key: str = ""
    #: 页脚（允许 HTML）
    footer_html: str = ""

    # ------------------------------------------------------------ 派生路径

    @property
    def prefix(self) -> str:
        raw = _normalize_prefix(self.path_prefix)
        return f"/{raw}" if raw else ""

    @property
    def api_prefix(self) -> str:
        return f"{self.prefix}/api"

    @property
    def gate_enabled(self) -> bool:
        return bool(self.admin_password)

    @property
    def footer(self) -> str:
        if self.footer_html.strip():
            return self.footer_html.strip()
        return "WXPUSH @ 2026"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wxpush.sqlite3"

    @property
    def key_path(self) -> Path:
        return self.data_dir / "secret.key"

    @property
    def on_https(self) -> bool:
        return self.cookie_secure or self.base_url.lower().startswith("https://")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ 环境变量

    @classmethod
    def from_env(cls) -> Settings:
        base_url = _env("BASE_URL") or ""
        return cls(
            data_dir=Path(_env("DATA_DIR") or "./data").expanduser(),
            host=_env("HOST") or "127.0.0.1",
            port=_int("PORT", 8000),
            base_url=base_url,
            path_prefix=_env("PATH_PREFIX") or "",
            admin_user=_env("ADMIN_USER") or "",
            admin_password=_env("ADMIN_PASSWORD") or "",
            session_ttl_hours=_int("SESSION_TTL_HOURS", 24 * 7),
            cookie_secure=_bool(
                "COOKIE_SECURE", base_url.lower().startswith("https://")
            ),
            wecom_base_url=_env("WECOM_BASE_URL") or "https://qyapi.weixin.qq.com",
            wecom_timeout_seconds=float(_env("WECOM_TIMEOUT_SECONDS") or 15),
            rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 120),
            max_payload_bytes=_int("MAX_PAYLOAD_KB", 64) * 1024,
            message_retention_days=_int("MESSAGE_RETENTION_DAYS", 180),
            purge_interval_seconds=_int("PURGE_INTERVAL_SECONDS", 24 * 3600),
            encryption_key=_env("ENCRYPTION_KEY") or "",
            footer_html=_env("FOOTER_HTML") or "",
        )
