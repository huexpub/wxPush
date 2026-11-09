"""页面路由与健康检查。"""

from __future__ import annotations


def test_healthz(client):
    res = client.get("/api/healthz")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_index_served_without_build(client):
    res = client.get("/")
    assert res.status_code == 200
    # 构建产物不存在时给说明页，而不是 404
    assert "WXPUSH" in res.text


def test_spa_fallback(client):
    res = client.get("/messages")
    assert res.status_code == 200


def test_built_assets_are_served_with_correct_mime(client):
    """构建产物存在时，index.html 引用的 JS/CSS 必须能按正确类型取到。

    这条曾经踩过坑：``/assets`` 前缀被路由吃掉后没补回去，结果资源 404，
    页面白屏 —— 而 index.html 本身是 200，很容易误判成「部署没问题」。
    """
    import re

    from wxpush.config import DIST_DIR

    index = DIST_DIR / "index.html"
    if not index.is_file():
        import pytest

        pytest.skip("前端还没构建")

    html = index.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="\./(assets/[^"]+)"', html)
    assert refs, "index.html 里没有 assets 引用？"

    for ref in refs:
        res = client.get(f"/{ref}")
        assert res.status_code == 200, f"{ref} -> {res.status_code}"
        expected = "javascript" if ref.endswith(".js") else "css"
        assert expected in res.headers["content-type"]
        assert "immutable" in res.headers.get("cache-control", "")


def test_prefix_keeps_assets_working(tmp_path):
    from fastapi.testclient import TestClient

    from wxpush.app import create_app
    from wxpush.config import DIST_DIR, Settings

    index = DIST_DIR / "index.html"
    if not index.is_file():
        import pytest

        pytest.skip("前端还没构建")

    import re

    settings = Settings(data_dir=tmp_path / "data", path_prefix="wxpush")
    with TestClient(create_app(settings)) as web:
        html = web.get("/wxpush/").text
        refs = re.findall(r'(?:src|href)="\./(assets/[^"]+)"', html)
        assert refs
        for ref in refs:
            assert web.get(f"/wxpush/{ref}").status_code == 200


def test_unknown_api_is_404(client):
    assert client.get("/api/nope").status_code == 404


def test_path_prefix(tmp_path):
    from fastapi.testclient import TestClient

    from wxpush.app import create_app
    from wxpush.config import Settings

    settings = Settings(
        data_dir=tmp_path / "data", admin_password="pw", path_prefix="wxpush"
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/wxpush/").status_code == 200
        assert client.get("/wxpush/api/healthz").status_code == 200
        assert client.get("/wxpush/api/auth/session").json()["gate"] is True
        # 前缀之外不提供 API
        assert client.get("/api/healthz").status_code == 404
