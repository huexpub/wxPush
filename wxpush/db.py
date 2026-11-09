"""SQLite 存储层。

为什么是 SQLite：单机部署，一个进程、一个数据目录，不需要额外服务。
写事务用 ``BEGIN IMMEDIATE``，避免两个请求同时抢同一条 webhook 的计数。

时间一律存 Unix 秒（整数）：比较、TTL 计算都不依赖时区/字符串格式。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 一个「应用」= 企业微信自建应用的三要素（企业ID / AgentId / Secret）
CREATE TABLE IF NOT EXISTS apps (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    corp_id        TEXT NOT NULL,
    agent_id       TEXT NOT NULL,
    secret_enc     TEXT NOT NULL,
    secret_hint    TEXT NOT NULL DEFAULT '',   -- 只存末 4 位，列表里给人辨认
    default_touser TEXT NOT NULL DEFAULT '',   -- 默认接收人，逗号分隔
    enabled        INTEGER NOT NULL DEFAULT 1,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL
);

-- 消息模板：text / markdown 的 content 是正文；
-- textcard / news 的 content 是 JSON（渲染后再按结构校验）。
CREATE TABLE IF NOT EXISTS templates (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    msg_type    TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

-- webhook：一个应用 + 一个模板 + 一个 key
CREATE TABLE IF NOT EXISTS hooks (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    app_id       TEXT NOT NULL REFERENCES apps (id) ON DELETE CASCADE,
    template_id  TEXT NOT NULL REFERENCES templates (id) ON DELETE CASCADE,
    key_hash     TEXT NOT NULL UNIQUE,        -- sha256(明文)，用于查找
    key_enc      TEXT NOT NULL,               -- 可逆加密，后台可复制
    key_hint     TEXT NOT NULL DEFAULT '',    -- wxp_xxxx…abcd
    enabled      INTEGER NOT NULL DEFAULT 1,
    use_count    INTEGER NOT NULL DEFAULT 0,
    last_used_at INTEGER,
    created_at   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hooks_app ON hooks (app_id);
CREATE INDEX IF NOT EXISTS idx_hooks_template ON hooks (template_id);

-- 消息历史：名称做冗余，删应用/模板后历史仍然可读
CREATE TABLE IF NOT EXISTS messages (
    id            TEXT PRIMARY KEY,
    hook_id       TEXT REFERENCES hooks (id) ON DELETE SET NULL,
    app_id        TEXT REFERENCES apps (id) ON DELETE SET NULL,
    template_id   TEXT REFERENCES templates (id) ON DELETE SET NULL,
    app_name      TEXT NOT NULL DEFAULT '',
    hook_name     TEXT NOT NULL DEFAULT '',
    template_name TEXT NOT NULL DEFAULT '',
    msg_type      TEXT NOT NULL,
    touser        TEXT NOT NULL DEFAULT '',
    payload       TEXT NOT NULL DEFAULT '{}',
    rendered      TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL CHECK (status IN ('success', 'failed')),
    error         TEXT,
    response      TEXT,
    ip            TEXT,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_created ON messages (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_app ON messages (app_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages (status, created_at DESC);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
    finally:
        conn.close()


#: 老库升级用的补丁（``CREATE TABLE IF NOT EXISTS`` 不会给已存在的表加列）。
#: 每一项都是 (列名, 列定义)，只加不改。
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "apps": [
        ("secret_hint", "TEXT NOT NULL DEFAULT ''"),
        ("default_touser", "TEXT NOT NULL DEFAULT ''"),
        ("enabled", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "hooks": [
        ("key_hint", "TEXT NOT NULL DEFAULT ''"),
        ("enabled", "INTEGER NOT NULL DEFAULT 1"),
        ("use_count", "INTEGER NOT NULL DEFAULT 0"),
        ("last_used_at", "INTEGER"),
    ],
    "messages": [
        ("response", "TEXT"),
        ("ip", "TEXT"),
        ("duration_ms", "INTEGER NOT NULL DEFAULT 0"),
    ],
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, definition in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
