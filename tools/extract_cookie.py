#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从微信 4.x（Radium/Chromium）本地 cookie 库中提取 lecture.tongji.edu.cn 的会话 cookie。

只能在本机、当前 Windows 用户下运行：Chromium 的 AES 密钥由 DPAPI 用当前用户身份保护。
用法:
    python extract_cookie.py <数据库副本目录> <Local State 路径> <输出 cookie.txt 路径>
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import pathlib
import sqlite3
import sys

from Cryptodome.Cipher import AES

HOST = "lecture.tongji.edu.cn"
CHROMIUM_EPOCH_OFFSET = 11644473600  # 1601-01-01 → 1970-01-01 秒


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_crypt32.CryptUnprotectData.restype = wt.BOOL


def dpapi_unprotect(data: bytes) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    src = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = DATA_BLOB()
    if not _crypt32.CryptUnprotectData(
        ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32.LocalFree(out.pbData)


def load_key(local_state: pathlib.Path) -> bytes:
    data = json.loads(local_state.read_text(encoding="utf-8"))
    blob = base64.b64decode(data["os_crypt"]["encrypted_key"])
    if blob[:5] != b"DPAPI":
        raise SystemExit("Local State 的密钥不是 DPAPI 格式，无法在本机解密")
    return dpapi_unprotect(blob[5:])


def decrypt_value(enc: bytes, key: bytes) -> str:
    if enc[:3] not in (b"v10", b"v11"):
        raise SystemExit(f"未知的加密版本: {enc[:3]!r}")
    body = enc[3:]
    nonce, rest = body[:12], body[12:]
    plain = AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(rest[:-16], rest[-16:])
    # Chromium 130+ 在明文前加了 32 字节域名绑定摘要
    if len(plain) > 32 and plain[:32] == hashlib.sha256(HOST.encode()).digest():
        plain = plain[32:]
    return plain.decode("utf-8")


def collect(copies: pathlib.Path) -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    for db in sorted(copies.glob("cookies_*")):
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            rows = con.execute(
                "select name, encrypted_value, last_access_utc from cookies where host_key=?",
                (HOST,),
            ).fetchall()
            con.close()
        except sqlite3.Error:
            continue
        for name, enc, last in rows:
            if enc:
                found.append((last or 0, name, enc.hex()))
    return found


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    copies, local_state, outfile = map(pathlib.Path, sys.argv[1:])

    key = load_key(local_state)
    entries = collect(copies)
    if not entries:
        print(f"[x] 没在微信数据库里找到 {HOST} 的 cookie，先在该页面登录一次")
        return 1

    # last_access_utc 是 Chromium 时间（1601 起微秒），取最新的一条
    latest = max(entries, key=lambda e: e[0])
    con_name = latest[1]
    value = decrypt_value(bytes.fromhex(latest[2]), key)

    outfile.write_text(f"{con_name}={value}", encoding="utf-8")
    print(f"[ok] 已写入 {outfile}")
    print(f"     {con_name} = {value[:8]}...{value[-4:]}（{len(value)} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
