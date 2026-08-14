#!/usr/bin/env python3
"""ADR 0019 Slice CO — existing identity callback ACE refuses spawn.

CM/CN walk A/OA allow ACEs and NULL DACL. Callback/conditional allow ACEs
(XA/ZA/XU) still grant Everyone/Users and were skipped. Slice CO refuses
those (and unknown ACE types). Dest ACL is never rewritten. Capability
``identity_key_callback_ace_refuse`` is true only on Windows / phase >= 92.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identity_callback_ace_refuse_lab.py
"""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x4
PROTECTED_DACL_SECURITY_INFORMATION = 0x8000_0000
SDDL_REVISION_1 = 1

CALLBACK_EVERYONE_SDDL = "D:P(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)(XA;;FR;;;WD;(TRUE))"


def _set_dacl_sddl(path: Path, sddl: str) -> None:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.ULONG),
    ]
    convert.restype = wintypes.BOOL

    get_dacl = advapi.GetSecurityDescriptorDacl
    get_dacl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL),
    ]
    get_dacl.restype = wintypes.BOOL

    set_info = advapi.SetNamedSecurityInfoW
    set_info.argtypes = [
        wintypes.LPWSTR,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    set_info.restype = ctypes.c_uint32

    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    sd = ctypes.c_void_p()
    if not convert(sddl, SDDL_REVISION_1, ctypes.byref(sd), None):
        raise OSError(ctypes.get_last_error(), "ConvertStringSecurityDescriptor")
    if not sd.value:
        raise OSError("ConvertStringSecurityDescriptor returned NULL SD")
    present = wintypes.BOOL(0)
    defaulted = wintypes.BOOL(0)
    dacl = ctypes.c_void_p()
    if not get_dacl(sd, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
        local_free(sd)
        raise OSError(ctypes.get_last_error(), "GetSecurityDescriptorDacl")
    if not present.value or not dacl.value:
        local_free(sd)
        raise OSError("SDDL produced NULL DACL")
    err = set_info(
        str(path),
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        dacl,
        None,
    )
    local_free(sd)
    if err != 0:
        raise OSError(err, "SetNamedSecurityInfoW callback ACE")


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    want = "windows_callback_ace_refuse" if os.name == "nt" else "unix_mode_covers"
    mod_strategy = str(getattr(abs_native, "IDENTITY_KEY_CALLBACK_ACE_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-id-cbace-") as td:
        key_path = Path(td) / "node.key"
        a = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            cap = a.capability_status()
            if os.name == "nt":
                if not cap.get("identity_key_callback_ace_refuse"):
                    print(f"FAIL: capability identity_key_callback_ace_refuse: {cap}")
                    return 1
            elif cap.get("identity_key_callback_ace_refuse"):
                print("FAIL: identity_key_callback_ace_refuse true on non-Windows")
                return 1
            if cap.get("identity_key_callback_ace_strategy") != want:
                print(
                    "FAIL: capability strategy "
                    f"{cap.get('identity_key_callback_ace_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 92:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            pid = a.peer_id
            first = key_path.read_bytes()
        finally:
            a.close()

        if os.name == "nt":
            _set_dacl_sddl(key_path, CALLBACK_EVERYONE_SDDL)
            try:
                abs_native.libp2p_node_new(
                    enable_mdns=False,
                    enable_reconnect=False,
                    key_path=str(key_path),
                )
                print("FAIL: callback Everyone ACE key was accepted")
                return 1
            except Exception as exc:
                msg = str(exc).lower()
                if not any(
                    token in msg
                    for token in ("dacl", "xa", "wd", "callback", "everyone", "ace")
                ):
                    print(f"FAIL: callback ACE error too vague: {exc}")
                    return 1
            if key_path.read_bytes() != first:
                print("FAIL: dest bytes changed after callback ACE refuse")
                return 1
            print(f"OK: identity callback ACE refuse peer_id={pid}")
        else:
            print(f"OK: identity callback ACE unix_mode_covers peer_id={pid}")

    print("OK: libp2p_rust_identity_callback_ace_refuse_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; callback/conditional allow ACE refuses "
        "spawn on Windows; no silent DACL rewrite; Unix covered by mode bits; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
