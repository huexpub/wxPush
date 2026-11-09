"""落库加密。

企业微信的 corpsecret 和 webhook key 都是「拿到就能发消息」的凭据，
不能明文躺在 SQLite 里（备份、误传、只读排查都会泄露）。

用 AES-256-GCM：
  * 密钥来自 ``WXPUSH_ENCRYPTION_KEY``（base64 32 字节），或首次启动时
    生成 ``data/secret.key``（0600）；
  * 每次加密用随机 nonce，密文 = base64(nonce + ciphertext)；
  * 解密失败说明换了数据目录却没带密钥，会直接报错而不是静默发空消息。

webhook key 还需要能按明文查找，所以库里另存一份 sha256（``key_hash``）。
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AAD = b"wxpush-v1"
_NONCE_SIZE = 12


class DecryptError(RuntimeError):
    """密文无法解开：通常是换了 ``data/secret.key``。"""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _read_key_file(path: Path) -> bytes:
    raw = path.read_bytes()
    if len(raw) != 32:
        # 旧版本（Windows）用文本模式写过密钥文件：每个 \n 都变成了 \r\n。
        # 反向替换后如果正好 32 字节，说明就是这个原因，直接兼容读取。
        repaired = raw.replace(b"\r\n", b"\n")
        if len(repaired) == 32:
            return repaired
        raise ValueError(f"{path} 内容不是 32 字节，请删除后重新启动以生成新密钥")
    return raw


def load_key(secret_path: Path, env_value: str = "") -> bytes:
    """读取 32 字节密钥。优先环境变量，其次文件，最后生成。"""
    if env_value:
        raw = _b64d(env_value.strip())
        if len(raw) != 32:
            raise ValueError("WXPUSH_ENCRYPTION_KEY 必须是 base64 的 32 字节")
        return raw

    if secret_path.exists():
        return _read_key_file(secret_path)

    secret_path.parent.mkdir(parents=True, exist_ok=True)
    raw = secrets.token_bytes(32)
    # O_EXCL：两个进程同时首次启动时只有一个能写成功。
    # O_BINARY 必须加 —— Windows 默认文本模式会把 \n 写成 \r\n，密钥就变成 33 字节。
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(secret_path, flags, 0o600)
    except FileExistsError:
        return _read_key_file(secret_path)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    return raw


class Cipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("AES-256 需要 32 字节密钥")
        self._key = key
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = secrets.token_bytes(_NONCE_SIZE)
        ct = self._aead.encrypt(nonce, plaintext.encode("utf-8"), AAD)
        return _b64e(nonce + ct)

    def decrypt(self, token: str) -> str:
        try:
            raw = _b64d(token)
        except ValueError as exc:
            raise DecryptError("密文格式不正确") from exc
        if len(raw) <= _NONCE_SIZE:
            raise DecryptError("密文长度不正确")
        nonce, ct = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
        try:
            return self._aead.decrypt(nonce, ct, AAD).decode("utf-8")
        except Exception as exc:  # InvalidTag 等
            raise DecryptError("解密失败：检查 data/secret.key 是否与数据库匹配") from exc


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def mask_key(key: str) -> str:
    """``wxp_abcdefghijkl…`` -> ``wxp_abcdef…wxyz``，日志/列表里用。"""
    if len(key) <= 14:
        return "****"
    return f"{key[:10]}…{key[-4:]}"
