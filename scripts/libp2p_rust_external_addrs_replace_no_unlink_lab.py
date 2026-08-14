#!/usr/bin/env python3
"""ADR 0019 Slice CD — persist replace without unlink-then-rename.

BQ wrote tmp+fsync then replaced dest. On Windows that used
``remove_file(dest)`` + ``rename`` (dest briefly missing). Slice CD uses
``MoveFileExW(REPLACE_EXISTING)`` on Windows and POSIX ``rename`` elsewhere.
Dest is never unlinked first. Still not POSIX inode-atomic on NTFS.
Capability ``external_addrs_replace_no_unlink`` / phase >= 81.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_external_addrs_replace_no_unlink_lab.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIRST = "/ip4/203.0.113.81/tcp/4081"
SECOND = "/ip4/203.0.113.82/tcp/4082"


def _wait(pred, timeout: float = 5.0, step: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return False


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    want = (
        "windows_movefileex_replace"
        if sys.platform == "win32"
        else "posix_rename"
    )
    mod_strategy = str(getattr(abs_native, "EXTERNAL_ADDRS_REPLACE_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-extreplace-") as td:
        store = Path(td) / "external_addrs.json"
        tmp = Path(str(store) + f".{os.getpid()}.tmp")
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            external_addrs_path=str(store),
        )
        try:
            cap = node.capability_status()
            if not cap.get("external_addrs_replace_no_unlink"):
                print(f"FAIL: capability external_addrs_replace_no_unlink: {cap}")
                return 1
            if cap.get("external_addrs_replace_strategy") != want:
                print(
                    f"FAIL: capability strategy {cap.get('external_addrs_replace_strategy')!r} "
                    f"!= {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 81:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1

            addrs = node.listen("/ip4/127.0.0.1/tcp/0")
            if not addrs:
                print("FAIL: empty listen")
                return 1
            if not _wait(lambda: addrs[0] in node.external_addrs(), timeout=4.0):
                print(f"FAIL: listen not external: {node.external_addrs()}")
                return 1
            # Slice BP: persist file is operator-advertised only (listen-derived
            # is not written). First add creates dest; second add replaces it.

            if not node.add_external_address(FIRST):
                print("FAIL: first advertised add returned False")
                return 1
            if not store.is_file():
                print("FAIL: dest missing after first persist")
                return 1
            if tmp.exists():
                print(f"FAIL: tmp leftover after first replace: {tmp}")
                return 1
            disk = json.loads(store.read_text(encoding="utf-8"))
            if FIRST not in list(disk.get("addrs") or []):
                print(f"FAIL: dest missing first advertised: {disk}")
                return 1

            if not node.add_external_address(SECOND):
                print("FAIL: second advertised add returned False")
                return 1
            if not store.is_file():
                print("FAIL: dest missing after second replace")
                return 1
            if tmp.exists():
                print("FAIL: tmp leftover after second replace")
                return 1
            disk2 = json.loads(store.read_text(encoding="utf-8"))
            got = list(disk2.get("addrs") or [])
            if FIRST not in got or SECOND not in got:
                print(f"FAIL: dest after second replace: {disk2}")
                return 1
            print(f"OK: replace_no_unlink strategy={want} dest={got}")
        finally:
            try:
                node.close()
            except Exception:
                pass

    print("OK: libp2p_rust_external_addrs_replace_no_unlink_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; persist replace without dest unlink; "
        "not POSIX inode-atomic on NTFS; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
