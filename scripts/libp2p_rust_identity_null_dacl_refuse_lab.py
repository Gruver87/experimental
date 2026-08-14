#!/usr/bin/env python3
"""ADR 0019 Slice CN — existing identity NULL DACL refuses spawn.

CM refuses Users/Everyone allow ACEs. A NULL DACL has *no* allow ACEs and
Windows treats that as grant-everyone. Slice CN refuses spawn when the DACL
is absent or NULL. Dest ACL is never rewritten. Capability
``identity_key_null_dacl_refuse`` is true only on Windows / phase >= 91.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identity_null_dacl_refuse_lab.py
"""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x4


def _set_null_dacl(path: Path) -> None:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    fn = advapi.SetNamedSecurityInfoW
    fn.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    fn.restype = ctypes.c_uint32
    err = fn(str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None, None, None)
    if err != 0:
        raise OSError(err, "SetNamedSecurityInfoW NULL DACL")


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    want = "windows_null_dacl_refuse" if os.name == "nt" else "unix_mode_covers"
    mod_strategy = str(getattr(abs_native, "IDENTITY_KEY_NULL_DACL_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-id-nulldacl-") as td:
        key_path = Path(td) / "node.key"
        a = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            cap = a.capability_status()
            if os.name == "nt":
                if not cap.get("identity_key_null_dacl_refuse"):
                    print(f"FAIL: capability identity_key_null_dacl_refuse: {cap}")
                    return 1
            elif cap.get("identity_key_null_dacl_refuse"):
                print("FAIL: identity_key_null_dacl_refuse true on non-Windows")
                return 1
            if cap.get("identity_key_null_dacl_strategy") != want:
                print(
                    "FAIL: capability strategy "
                    f"{cap.get('identity_key_null_dacl_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 91:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            pid = a.peer_id
            first = key_path.read_bytes()
        finally:
            a.close()

        if os.name == "nt":
            _set_null_dacl(key_path)
            try:
                abs_native.libp2p_node_new(
                    enable_mdns=False,
                    enable_reconnect=False,
                    key_path=str(key_path),
                )
                print("FAIL: NULL DACL key was accepted")
                return 1
            except Exception as exc:
                msg = str(exc).lower()
                if "null" not in msg and "dacl" not in msg:
                    print(f"FAIL: NULL DACL error too vague: {exc}")
                    return 1
            if key_path.read_bytes() != first:
                print("FAIL: dest bytes changed after NULL DACL refuse")
                return 1
            print(f"OK: identity NULL DACL refuse peer_id={pid}")
        else:
            print(f"OK: identity NULL DACL unix_mode_covers peer_id={pid}")

    print("OK: libp2p_rust_identity_null_dacl_refuse_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; NULL DACL refuses spawn on Windows; "
        "no silent DACL rewrite; Unix covered by mode bits; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
