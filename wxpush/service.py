"""唯一的业务写入口。

HTTP 层只做参数校验与状态码映射，所有判定在这里：

    resolve_hook(key)      -> hook + app + template（含解密 secret）
    deliver(hook, data)    -> 渲染模板、发送、落历史

webhook key 的形态是 ``wxp_<24 位 url-safe>``。库里存两份：
  * ``key_hash`` = sha256(明文)，用于 O(1) 查找；
  * ``key_enc`` = AES-GCM(明文)，用于后台「复制 key」。

历史记录里冗余了 app / hook / template 的名字，删掉配置后旧记录仍然可读。
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .crypto import Cipher, DecryptError, mask_key, sha256_text
from .db import session, transaction
from .templating import TemplateError, placeholders, render_content
from .wecom import MSG_TYPES, WeComClient, WeComError


class ServiceError(Exception):
    """业务错误。``code`` 同时作为 API 的 ``error`` 字段。"""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _now() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _app_view(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "corp_id": row["corp_id"],
        "agent_id": row["agent_id"],
        "secret_hint": row["secret_hint"],
        "default_touser": row["default_touser"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _template_view(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "msg_type": row["msg_type"],
        "content": row["content"],
        "variables": placeholders(row["content"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _hook_view(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "app_id": row["app_id"],
        "template_id": row["template_id"],
        "key_hint": row["key_hint"],
        "enabled": bool(row["enabled"]),
        "use_count": row["use_count"],
        "last_used_at": row["last_used_at"],
        "created_at": row["created_at"],
    }


def _message_view(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "hook_id": row["hook_id"],
        "app_id": row["app_id"],
        "template_id": row["template_id"],
        "app_name": row["app_name"],
        "hook_name": row["hook_name"],
        "template_name": row["template_name"],
        "msg_type": row["msg_type"],
        "touser": row["touser"],
        "payload": json.loads(row["payload"] or "{}"),
        "rendered": row["rendered"],
        "status": row["status"],
        "error": row["error"],
        "response": row["response"],
        "ip": row["ip"],
        "duration_ms": row["duration_ms"],
        "created_at": row["created_at"],
    }


@dataclass(slots=True)
class ResolvedHook:
    hook_id: str
    hook_name: str
    app_id: str
    app_name: str
    corp_id: str
    agent_id: str
    secret: str
    default_touser: str
    template_id: str
    template_name: str
    msg_type: str
    content: str


class Service:
    def __init__(self, settings: Settings, cipher: Cipher, client: WeComClient | None = None) -> None:
        self.settings = settings
        self.cipher = cipher
        self.client = client or WeComClient(
            settings.wecom_base_url, settings.wecom_timeout_seconds
        )

    # ================================================================ 应用

    def list_apps(self) -> list[dict[str, Any]]:
        with session(self.settings.db_path) as conn:
            rows = conn.execute("SELECT * FROM apps ORDER BY created_at DESC").fetchall()
        return [_app_view(row) for row in rows]

    def _require_app(self, conn, app_id: str):
        row = conn.execute("SELECT * FROM apps WHERE id = ?", (app_id,)).fetchone()
        if not row:
            raise ServiceError("app_not_found", "应用不存在", 404)
        return row

    def create_app(
        self, *, name: str, corp_id: str, agent_id: str, secret: str, default_touser: str = ""
    ) -> dict[str, Any]:
        name, corp_id, agent_id, secret = (
            name.strip(),
            corp_id.strip(),
            agent_id.strip(),
            secret.strip(),
        )
        if not name:
            raise ServiceError("invalid_name", "应用名称不能为空")
        if not corp_id:
            raise ServiceError("invalid_corp_id", "企业 ID 不能为空")
        if not agent_id:
            raise ServiceError("invalid_agent_id", "AgentId 不能为空")
        if not secret:
            raise ServiceError("invalid_secret", "Secret 不能为空")

        now = _now()
        app_id = _new_id("app")
        with transaction(self.settings.db_path) as conn:
            conn.execute(
                """INSERT INTO apps
                   (id, name, corp_id, agent_id, secret_enc, secret_hint,
                    default_touser, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    app_id,
                    name,
                    corp_id,
                    agent_id,
                    self.cipher.encrypt(secret),
                    mask_key(secret),
                    default_touser.strip(),
                    now,
                    now,
                ),
            )
            row = self._require_app(conn, app_id)
        return _app_view(row)

    def update_app(self, app_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"name", "corp_id", "agent_id", "secret", "default_touser", "enabled"}
        updates: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "secret":
                value = str(value).strip()
                if value:
                    updates["secret_enc"] = self.cipher.encrypt(value)
                    updates["secret_hint"] = mask_key(value)
                continue
            if key == "enabled":
                updates[key] = 1 if value else 0
                continue
            updates[key] = str(value).strip()

        if not updates:
            with session(self.settings.db_path) as conn:
                return _app_view(self._require_app(conn, app_id))

        updates["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with transaction(self.settings.db_path) as conn:
            self._require_app(conn, app_id)
            conn.execute(
                f"UPDATE apps SET {assignments} WHERE id = ?",
                (*updates.values(), app_id),
            )
            row = self._require_app(conn, app_id)
        return _app_view(row)

    def delete_app(self, app_id: str) -> None:
        with transaction(self.settings.db_path) as conn:
            self._require_app(conn, app_id)
            conn.execute("DELETE FROM apps WHERE id = ?", (app_id,))

    # ================================================================ 模板

    def list_templates(self) -> list[dict[str, Any]]:
        with session(self.settings.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM templates ORDER BY created_at DESC"
            ).fetchall()
        return [_template_view(row) for row in rows]

    def _require_template(self, conn, template_id: str):
        row = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        if not row:
            raise ServiceError("template_not_found", "模板不存在", 404)
        return row

    def create_template(
        self, *, name: str, msg_type: str, content: str, description: str = ""
    ) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ServiceError("invalid_name", "模板名称不能为空")
        _check_template(msg_type, content)
        now = _now()
        template_id = _new_id("tpl")
        with transaction(self.settings.db_path) as conn:
            conn.execute(
                """INSERT INTO templates
                   (id, name, description, msg_type, content, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (template_id, name, description.strip(), msg_type, content, now, now),
            )
            row = self._require_template(conn, template_id)
        return _template_view(row)

    def update_template(self, template_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"name", "description", "msg_type", "content"}
        updates = {
            key: (str(value).strip() if key != "content" else str(value))
            for key, value in fields.items()
            if key in allowed and value is not None
        }
        if not updates:
            with session(self.settings.db_path) as conn:
                return _template_view(self._require_template(conn, template_id))

        with transaction(self.settings.db_path) as conn:
            current = self._require_template(conn, template_id)
            msg_type = updates.get("msg_type", current["msg_type"])
            content = updates.get("content", current["content"])
            _check_template(msg_type, content)
            updates["updated_at"] = _now()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE templates SET {assignments} WHERE id = ?",
                (*updates.values(), template_id),
            )
            row = self._require_template(conn, template_id)
        return _template_view(row)

    def delete_template(self, template_id: str) -> None:
        with transaction(self.settings.db_path) as conn:
            self._require_template(conn, template_id)
            conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))

    # ================================================================ webhook

    def list_hooks(self) -> list[dict[str, Any]]:
        with session(self.settings.db_path) as conn:
            rows = conn.execute(
                """SELECT h.*, a.name AS app_name, t.name AS template_name, t.msg_type
                   FROM hooks h
                   LEFT JOIN apps a ON a.id = h.app_id
                   LEFT JOIN templates t ON t.id = h.template_id
                   ORDER BY h.created_at DESC"""
            ).fetchall()
        out = []
        for row in rows:
            item = _hook_view(row)
            item["app_name"] = row["app_name"] or "（已删除）"
            item["template_name"] = row["template_name"] or "（已删除）"
            item["msg_type"] = row["msg_type"] or ""
            out.append(item)
        return out

    def create_hook(self, *, name: str, app_id: str, template_id: str) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ServiceError("invalid_name", "webhook 名称不能为空")
        key = f"wxp_{secrets.token_urlsafe(24)}"
        hook_id = _new_id("hook")
        now = _now()
        with transaction(self.settings.db_path) as conn:
            self._require_app(conn, app_id)
            self._require_template(conn, template_id)
            conn.execute(
                """INSERT INTO hooks
                   (id, name, app_id, template_id, key_hash, key_enc, key_hint,
                    enabled, use_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?)""",
                (
                    hook_id,
                    name,
                    app_id,
                    template_id,
                    sha256_text(key),
                    self.cipher.encrypt(key),
                    mask_key(key),
                    now,
                ),
            )
        return {"id": hook_id, "name": name, "key": key, "key_hint": mask_key(key)}

    def reveal_key(self, hook_id: str) -> str:
        with session(self.settings.db_path) as conn:
            row = conn.execute("SELECT key_enc FROM hooks WHERE id = ?", (hook_id,)).fetchone()
        if not row:
            raise ServiceError("hook_not_found", "webhook 不存在", 404)
        return self.cipher.decrypt(row["key_enc"])

    def update_hook(self, hook_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"name", "app_id", "template_id", "enabled"}
        updates = {}
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            updates[key] = (1 if value else 0) if key == "enabled" else str(value).strip()
        if not updates:
            with session(self.settings.db_path) as conn:
                row = conn.execute("SELECT * FROM hooks WHERE id = ?", (hook_id,)).fetchone()
            if not row:
                raise ServiceError("hook_not_found", "webhook 不存在", 404)
            return _hook_view(row)

        with transaction(self.settings.db_path) as conn:
            if conn.execute("SELECT 1 FROM hooks WHERE id = ?", (hook_id,)).fetchone() is None:
                raise ServiceError("hook_not_found", "webhook 不存在", 404)
            if "app_id" in updates:
                self._require_app(conn, updates["app_id"])
            if "template_id" in updates:
                self._require_template(conn, updates["template_id"])
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE hooks SET {assignments} WHERE id = ?",
                (*updates.values(), hook_id),
            )
            row = conn.execute("SELECT * FROM hooks WHERE id = ?", (hook_id,)).fetchone()
        return _hook_view(row)

    def rotate_hook(self, hook_id: str) -> dict[str, Any]:
        key = f"wxp_{secrets.token_urlsafe(24)}"
        with transaction(self.settings.db_path) as conn:
            row = conn.execute("SELECT * FROM hooks WHERE id = ?", (hook_id,)).fetchone()
            if not row:
                raise ServiceError("hook_not_found", "webhook 不存在", 404)
            conn.execute(
                "UPDATE hooks SET key_hash = ?, key_enc = ?, key_hint = ? WHERE id = ?",
                (sha256_text(key), self.cipher.encrypt(key), mask_key(key), hook_id),
            )
        return {"id": hook_id, "key": key, "key_hint": mask_key(key)}

    def delete_hook(self, hook_id: str) -> None:
        with transaction(self.settings.db_path) as conn:
            if conn.execute("SELECT 1 FROM hooks WHERE id = ?", (hook_id,)).fetchone() is None:
                raise ServiceError("hook_not_found", "webhook 不存在", 404)
            conn.execute("DELETE FROM hooks WHERE id = ?", (hook_id,))

    # ================================================================ 投递

    def resolve_hook(self, key: str) -> ResolvedHook:
        """按明文 key 找到 hook，并把应用/模板展开。"""
        if not key or not key.startswith("wxp_"):
            raise ServiceError("invalid_key", "webhook key 格式不正确", 404)
        with session(self.settings.db_path) as conn:
            row = conn.execute(
                """SELECT h.id AS hook_id, h.name AS hook_name, h.enabled AS hook_enabled,
                          a.id AS app_id, a.name AS app_name, a.corp_id, a.agent_id,
                          a.secret_enc, a.default_touser, a.enabled AS app_enabled,
                          t.id AS template_id, t.name AS template_name,
                          t.msg_type, t.content
                   FROM hooks h
                   JOIN apps a ON a.id = h.app_id
                   JOIN templates t ON t.id = h.template_id
                   WHERE h.key_hash = ?""",
                (sha256_text(key),),
            ).fetchone()
        if not row:
            raise ServiceError("hook_not_found", "webhook key 无效", 404)
        if not row["hook_enabled"]:
            raise ServiceError("hook_disabled", "webhook 已停用", 403)
        if not row["app_enabled"]:
            raise ServiceError("app_disabled", "关联的应用已停用", 403)
        try:
            secret = self.cipher.decrypt(row["secret_enc"])
        except DecryptError as exc:
            raise ServiceError("secret_unreadable", str(exc), 500) from exc
        return ResolvedHook(
            hook_id=row["hook_id"],
            hook_name=row["hook_name"],
            app_id=row["app_id"],
            app_name=row["app_name"],
            corp_id=row["corp_id"],
            agent_id=row["agent_id"],
            secret=secret,
            default_touser=row["default_touser"] or "",
            template_id=row["template_id"],
            template_name=row["template_name"],
            msg_type=row["msg_type"],
            content=row["content"],
        )

    def deliver(
        self,
        hook: ResolvedHook,
        data: dict[str, Any],
        *,
        touser: str = "",
        ip: str = "",
    ) -> dict[str, Any]:
        """渲染 + 发送 + 落历史。任何分支都会写一条记录。"""
        started = time.monotonic()
        audience = (touser or hook.default_touser or "@all").strip()
        status, error, rendered, response = "success", None, "", ""
        errcode: int | None = None

        try:
            rendered = render_content(hook.msg_type, hook.content, data)
        except TemplateError as exc:
            status, error = "failed", f"模板错误：{exc}"
            rendered = ""
        else:
            try:
                result = self.client.send(
                    corp_id=hook.corp_id,
                    agent_id=hook.agent_id,
                    secret=hook.secret,
                    msg_type=hook.msg_type,
                    content=rendered,
                    touser=audience,
                )
                response = result.response
                errcode = result.errcode
                if not result.ok:
                    status = "failed"
                    error = f"企业微信错误 {result.errcode}：{result.errmsg}"
                    if errcode == 81013:
                        error += "（接收人不在应用可见范围内）"
            except WeComError as exc:
                status = "failed"
                error = str(exc)
                response = exc.detail

        duration_ms = int((time.monotonic() - started) * 1000)
        message_id = _new_id("msg")
        with transaction(self.settings.db_path) as conn:
            conn.execute(
                """INSERT INTO messages
                   (id, hook_id, app_id, template_id, app_name, hook_name, template_name,
                    msg_type, touser, payload, rendered, status, error, response, ip,
                    duration_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message_id,
                    hook.hook_id,
                    hook.app_id,
                    hook.template_id,
                    hook.app_name,
                    hook.hook_name,
                    hook.template_name,
                    hook.msg_type,
                    audience,
                    json.dumps(data, ensure_ascii=False),
                    rendered,
                    status,
                    error,
                    response,
                    ip,
                    duration_ms,
                    _now(),
                ),
            )
            conn.execute(
                "UPDATE hooks SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                (_now(), hook.hook_id),
            )

        if status == "failed":
            raise ServiceError("send_failed", error or "发送失败", 502)
        return {
            "id": message_id,
            "status": status,
            "msg_type": hook.msg_type,
            "touser": audience,
            "rendered": rendered,
            "duration_ms": duration_ms,
        }

    # ================================================================ 历史

    def list_messages(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str = "",
        app_id: str = "",
        hook_id: str = "",
        query: str = "",
    ) -> dict[str, Any]:
        where, params = [], []
        if status in {"success", "failed"}:
            where.append("status = ?")
            params.append(status)
        if app_id:
            where.append("app_id = ?")
            params.append(app_id)
        if hook_id:
            where.append("hook_id = ?")
            params.append(hook_id)
        if query.strip():
            where.append("(rendered LIKE ? OR payload LIKE ? OR error LIKE ?)")
            needle = f"%{query.strip()}%"
            params.extend([needle, needle, needle])
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        with session(self.settings.db_path) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM messages {clause}", params
            ).fetchone()["n"]
            rows = conn.execute(
                f"""SELECT * FROM messages {clause}
                    ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [_message_view(row) for row in rows],
        }

    def get_message(self, message_id: str) -> dict[str, Any]:
        with session(self.settings.db_path) as conn:
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if not row:
            raise ServiceError("message_not_found", "消息记录不存在", 404)
        return _message_view(row)

    def delete_message(self, message_id: str) -> None:
        with transaction(self.settings.db_path) as conn:
            conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))

    def clear_messages(self) -> int:
        with transaction(self.settings.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
            conn.execute("DELETE FROM messages")
        return count

    def resend(self, message_id: str) -> dict[str, Any]:
        record = self.get_message(message_id)
        if not record["hook_id"]:
            raise ServiceError("hook_missing", "原 webhook 已删除，无法重发", 409)
        with session(self.settings.db_path) as conn:
            row = conn.execute(
                "SELECT key_enc FROM hooks WHERE id = ?", (record["hook_id"],)
            ).fetchone()
        if not row:
            raise ServiceError("hook_missing", "原 webhook 已删除，无法重发", 409)
        hook = self.resolve_hook(self.cipher.decrypt(row["key_enc"]))
        payload = record["payload"] if isinstance(record["payload"], dict) else {}
        return self.deliver(hook, payload, touser=record["touser"])

    def stats(self) -> dict[str, Any]:
        now = _now()
        day_ago = now - 86400
        week_ago = now - 7 * 86400
        with session(self.settings.db_path) as conn:
            apps = conn.execute("SELECT COUNT(*) AS n FROM apps").fetchone()["n"]
            templates = conn.execute("SELECT COUNT(*) AS n FROM templates").fetchone()["n"]
            hooks = conn.execute("SELECT COUNT(*) AS n FROM hooks").fetchone()["n"]
            total = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
            today = conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE created_at >= ?", (day_ago,)
            ).fetchone()["n"]
            week = conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE created_at >= ?", (week_ago,)
            ).fetchone()["n"]
            failed = conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE status = 'failed' AND created_at >= ?",
                (week_ago,),
            ).fetchone()["n"]
            recent = conn.execute(
                """SELECT id, app_name, hook_name, msg_type, status, created_at
                   FROM messages ORDER BY created_at DESC, rowid DESC LIMIT 8"""
            ).fetchall()
        return {
            "apps": apps,
            "templates": templates,
            "hooks": hooks,
            "messages": total,
            "messages_24h": today,
            "messages_7d": week,
            "failed_7d": failed,
            "recent": [dict(row) for row in recent],
        }

    def purge_messages(self) -> int:
        days = self.settings.message_retention_days
        if days <= 0:
            return 0
        cutoff = _now() - days * 86400
        with transaction(self.settings.db_path) as conn:
            cur = conn.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
            return cur.rowcount or 0


def _check_template(msg_type: str, content: str) -> None:
    from .templating import validate_template

    if msg_type not in MSG_TYPES:
        raise ServiceError("invalid_msg_type", f"不支持的消息类型：{msg_type}")
    try:
        validate_template(msg_type, content)
    except TemplateError as exc:
        raise ServiceError("invalid_template", str(exc)) from exc
