#!/usr/bin/env python3
"""ADR 0019 Slice CG — parent-directory fsync after persist replace.

tmp+fsync+replace (BQ/CD) still leaves a POSIX crash window: the directory
entry may be only in cache. Slice CG fsyncs the parent after replace
(POSIX directory fd; Windows ``FlushFileBuffers`` on a directory handle).
NTFS replace is still not POSIX inode-atomic. Capability
``persist_parent_dir_fsync`` / phase >= 84.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_persist_parent_dir_fsync_lab.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIRST = "/ip4/203.0.113.84/tcp/4084"
SECOND = "/ip4/203.0.113.85/tcp/4085"


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
        "windows_dir_flushfilebuffers"
        if sys.platform == "win32"
        else "posix_dir_fsync"
    )
    mod_strategy = str(getattr(abs_native, "PERSIST_PARENT_DIR_FSYNC_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-dirfsync-") as td:
        store = Path(td) / "external_addrs.json"
        key_path = Path(td) / "node.key"
        tmp = Path(str(store) + ".tmp")
        key_tmp = Path(str(key_path) + ".tmp")
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
            external_addrs_path=str(store),
        )
        try:
            cap = node.capability_status()
            if not cap.get("persist_parent_dir_fsync"):
                print(f"FAIL: capability persist_parent_dir_fsync: {cap}")
                return 1
            if cap.get("persist_parent_dir_fsync_strategy") != want:
                print(
                    f"FAIL: capability strategy "
                    f"{cap.get('persist_parent_dir_fsync_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 84:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            if not key_path.is_file():
                print("FAIL: identity dest missing after first-create")
                return 1
            if key_tmp.exists():
                print(f"FAIL: identity tmp leftover: {key_tmp}")
                return 1

            addrs = node.listen("/ip4/127.0.0.1/tcp/0")
            if not addrs:
                print("FAIL: empty listen")
                return 1
            if not _wait(lambda: addrs[0] in node.external_addrs(), timeout=4.0):
                print(f"FAIL: listen not external: {node.external_addrs()}")
                return 1

            if not node.add_external_address(FIRST):
                print("FAIL: first advertised add returned False")
                return 1
            if not store.is_file():
                print("FAIL: dest missing after first persist")
                return 1
            if tmp.exists():
                print(f"FAIL: tmp leftover after first persist: {tmp}")
                return 1

            if not node.add_external_address(SECOND):
                print("FAIL: second advertised add returned False")
                return 1
            if not store.is_file():
                print("FAIL: dest missing after replace")
                return 1
            if tmp.exists():
                print("FAIL: tmp leftover after replace")
                return 1
            disk = json.loads(store.read_text(encoding="utf-8"))
            got = list(disk.get("addrs") or [])
            if FIRST not in got or SECOND not in got:
                print(f"FAIL: dest after replace: {disk}")
                return 1
            print(f"OK: parent_dir_fsync strategy={want} dest={got}")
        finally:
            try:
                node.close()
            except Exception:
                pass

    print("OK: libp2p_rust_persist_parent_dir_fsync_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; parent dir fsync after replace; "
        "not POSIX inode-atomic on NTFS; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
