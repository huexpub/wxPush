"""模板渲染与结构校验。"""

from __future__ import annotations

import json

import pytest

from wxpush.templating import (
    TemplateError,
    placeholders,
    render_content,
    render_string,
    validate_template,
)


def test_render_plain_text():
    assert render_string("{{ title }}: {{ content }}", {"title": "构建", "content": "ok"}) == "构建: ok"


def test_render_missing_becomes_empty():
    assert render_string("A{{ nope }}B", {}) == "AB"


def test_render_default_value():
    assert render_string("{{ nope | default \"未知\" }}", {}) == "未知"
    assert render_string("{{ title | default \"未知\" }}", {"title": "有值"}) == "有值"


def test_render_nested_path():
    data = {"repo": {"name": "bfs", "branch": "main"}}
    assert render_string("{{ repo.name }}@{{ repo.branch }}", data) == "bfs@main"


def test_render_dict_and_bool():
    assert render_string("{{ flag }}", {"flag": True}) == "true"
    assert render_string("{{ obj }}", {"obj": {"a": 1}}) == '{"a": 1}'


def test_placeholders_dedup():
    assert placeholders("{{ a }} {{ b }} {{ a }}") == ["a", "b"]


def test_render_content_text():
    assert render_content("text", "{{ x }}", {"x": "1"}) == "1"


def test_render_content_rejects_blank_result():
    with pytest.raises(TemplateError):
        render_content("text", "{{ missing }}", {})


def test_render_textcard_validates_structure():
    content = json.dumps({"title": "{{ t }}", "description": "{{ d }}", "url": "{{ u }}"})
    rendered = render_content("textcard", content, {"t": "标题", "d": "内容", "u": "https://x.y"})
    parsed = json.loads(rendered)
    assert parsed["title"] == "标题"


def test_render_textcard_missing_field():
    content = json.dumps({"title": "{{ t }}"})
    with pytest.raises(TemplateError, match="缺少字段"):
        render_content("textcard", content, {"t": "标题"})


def test_render_news_article_limit():
    articles = [{"title": "t", "url": "u"} for _ in range(9)]
    with pytest.raises(TemplateError, match="最多 8 条"):
        render_content("news", json.dumps({"articles": articles}), {})


def test_validate_template_accepts_bad_placeholder_positions():
    # 占位符在 JSON 的键位置会渲染成非法 JSON —— 保存时就该报错
    with pytest.raises(TemplateError):
        validate_template("textcard", '{"{{ key }}": "v"}')


def test_validate_template_rejects_unknown_type():
    with pytest.raises(TemplateError):
        validate_template("video", "x")


def test_validate_template_rejects_empty():
    with pytest.raises(TemplateError):
        validate_template("text", "   ")
