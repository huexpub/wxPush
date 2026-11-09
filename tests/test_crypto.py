"""加密与密钥文件。"""

from __future__ import annotations

import base64

import pytest

from wxpush.crypto import Cipher, DecryptError, load_key, mask_key, sha256_text


def test_roundtrip():
    cipher = Cipher(b"k" * 32)
    assert cipher.decrypt(cipher.encrypt("企业微信 secret")) == "企业微信 secret"


def test_nonce_is_random():
    cipher = Cipher(b"k" * 32)
    assert cipher.encrypt("same") != cipher.encrypt("same")


def test_wrong_key_raises():
    encrypted = Cipher(b"a" * 32).encrypt("value")
    with pytest.raises(DecryptError):
        Cipher(b"b" * 32).decrypt(encrypted)


def test_load_key_creates_file(tmp_path):
    path = tmp_path / "secret.key"
    key = load_key(path)
    assert len(key) == 32
    assert path.exists()
    # 第二次读到的必须是同一个
    assert load_key(path) == key


def test_load_key_repairs_text_mode_file(tmp_path):
    """Windows 文本模式写入会把 \\n 变成 \\r\\n，读回来要能自动修正。"""
    path = tmp_path / "secret.key"
    original = bytes(range(32))  # 第 11 个字节正好是 0x0A
    path.write_bytes(original.replace(b"\n", b"\r\n"))
    assert len(path.read_bytes()) == 33
    assert load_key(path) == original


def test_load_key_rejects_garbage(tmp_path):
    path = tmp_path / "secret.key"
    path.write_bytes(b"not-a-key")
    with pytest.raises(ValueError):
        load_key(path)


def test_load_key_from_env(tmp_path):
    raw = b"z" * 32
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert load_key(tmp_path / "nope.key", encoded) == raw


def test_load_key_rejects_bad_env(tmp_path):
    with pytest.raises(ValueError):
        load_key(tmp_path / "x.key", base64.urlsafe_b64encode(b"short").decode())


def test_mask_and_hash():
    key = "wxp_abcdefghijklmnopqrstuvwx"
    assert mask_key(key).endswith(key[-4:])
    assert mask_key("short") == "****"
    assert sha256_text("a") == sha256_text("a")
    assert sha256_text("a") != sha256_text("b")
