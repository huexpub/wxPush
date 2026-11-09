"""消息模板：极简 ``{{ var }}`` 渲染。

为什么不用 Jinja2：
  * 模板内容来自后台编辑器，我们只需要「取一个字段贴进去」；
  * Jinja2 的表达式、过滤器、include 都是攻击面，而这里没有那个需求；
  * 自己实现 60 行，行为完全可预期，也好做结构校验。

支持：
    {{ name }}            取变量，缺失时用空串
    {{ name | default "无" }}   缺失时用给定默认值
    {{ payload.a.b }}     点号取嵌套字段

不支持循环/条件 —— 需要重复的行由调用方拼好再传进来。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .wecom import MSG_TYPES

_TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*(?:\|\s*default\s+\"([^\"]*)\")?\s*\}\}")


class TemplateError(ValueError):
    """模板写错了（语法或结构）。"""


def _lookup(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_string(template: str, data: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        path, fallback = match.group(1), match.group(2)
        value = _lookup(data, path)
        if value is None or value == "":
            return fallback if fallback is not None else ""
        return _stringify(value)

    return _TOKEN.sub(replace, template)


def placeholders(template: str) -> list[str]:
    """模板里出现的变量名（用于界面提示「这个模板需要哪些 key」）。"""
    seen: list[str] = []
    for match in _TOKEN.finditer(template):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def render_content(msg_type: str, content: str, data: dict[str, Any]) -> str:
    """渲染模板正文。

    text / markdown 直接替换；textcard / news 的 content 是 JSON 字符串，
    替换后再解析 + 校验结构 —— 这样「拼错的 JSON」会在保存模板时就报错，
    而不是等到线上推送失败。
    """
    if msg_type not in MSG_TYPES:
        raise TemplateError(f"不支持的消息类型：{msg_type}")
    if msg_type in {"text", "markdown"}:
        rendered = render_string(content, data)
        if not rendered.strip():
            raise TemplateError("渲染结果为空")
        return rendered

    rendered = render_string(content, data)
    try:
        parsed = json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise TemplateError(f"模板渲染后不是合法 JSON：{exc.msg}") from exc
    validate_structure(msg_type, parsed)
    return json.dumps(parsed, ensure_ascii=False)


def _require(obj: dict[str, Any], fields: tuple[str, ...], where: str) -> None:
    if not isinstance(obj, dict):
        raise TemplateError(f"{where} 必须是对象")
    for field in fields:
        if field not in obj:
            raise TemplateError(f"{where} 缺少字段 {field}")


def validate_structure(msg_type: str, payload: Any) -> None:
    """按企业微信文档校验 textcard / news 的必填字段。"""
    if msg_type == "textcard":
        _require(payload, ("title", "description", "url"), "textcard")
        return
    if msg_type == "news":
        _require(payload, ("articles",), "news")
        articles = payload.get("articles")
        if not isinstance(articles, list) or not articles:
            raise TemplateError("news.articles 必须是非空数组")
        if len(articles) > 8:
            raise TemplateError("news.articles 最多 8 条")
        for index, article in enumerate(articles, start=1):
            _require(article, ("title", "url"), f"articles[{index}]")


def validate_template(msg_type: str, content: str) -> None:
    """保存模板时的静态检查：用示例值渲染一遍，能过就认为结构没问题。"""
    if msg_type not in MSG_TYPES:
        raise TemplateError(f"不支持的消息类型：{msg_type}")
    if msg_type in {"text", "markdown"}:
        if not content.strip():
            raise TemplateError("模板内容不能为空")
        return
    sample = {
        "title": "示例标题",
        "description": "示例内容",
        "url": "https://example.com",
        "btntxt": "详情",
        "articles": [{"title": "示例标题", "description": "示例内容", "url": "https://example.com", "picurl": ""}],
    }
    # 模板里的 {{ var }} 在 JSON 里通常是字符串位置，直接替换成示例值即可
    merged = {**sample}
    probe = render_string(content, merged)
    try:
        parsed = json.loads(probe)
    except json.JSONDecodeError as exc:
        raise TemplateError(f"模板不是合法 JSON：{exc.msg}") from exc
    validate_structure(msg_type, parsed)
