#!/usr/bin/env python3
"""ADR 0019 Slice CJ — fsync newly created persist directories.

CG fsyncs the file's parent after replace. If that parent was just created,
a crash can still drop the new dirent in the grandparent. Slice CJ
``create_dir_all`` then fsyncs created dirs and the first existing ancestor
(volume roots skipped). Same dir-fsync primitive as CG. NTFS is still not
POSIX inode-atomic. Capability ``persist_mkdir_fsync`` / phase >= 87.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_persist_mkdir_fsync_lab.py
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

ADDR = "/ip4/203.0.113.87/tcp/4087"


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

    want = str(getattr(abs_native, "PERSIST_PARENT_DIR_FSYNC_STRATEGY", ""))
    mod_strategy = str(getattr(abs_native, "PERSIST_MKDIR_FSYNC_STRATEGY", ""))
    if not want or mod_strategy != want:
        print(f"FAIL: mkdir strategy {mod_strategy!r} != parent {want!r}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-mkdirfsync-") as td:
        nested = Path(td) / "a" / "b" / "c"
        store = nested / "external_addrs.json"
        key_path = nested / "node.key"
        tmp = Path(str(store) + f".{os.getpid()}.tmp")
        if nested.exists():
            print("FAIL: nested persist dir already existed")
            return 1
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
            external_addrs_path=str(store),
        )
        try:
            cap = node.capability_status()
            if not cap.get("persist_mkdir_fsync"):
                print(f"FAIL: capability persist_mkdir_fsync: {cap}")
                return 1
            if cap.get("persist_mkdir_fsync_strategy") != want:
                print(
                    f"FAIL: capability strategy "
                    f"{cap.get('persist_mkdir_fsync_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 87:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            if not key_path.is_file():
                print("FAIL: nested identity dest missing")
                return 1
            addrs = node.listen("/ip4/127.0.0.1/tcp/0")
            if not addrs:
                print("FAIL: empty listen")
                return 1
            if not _wait(lambda: addrs[0] in node.external_addrs(), timeout=4.0):
                print(f"FAIL: listen not external: {node.external_addrs()}")
                return 1
            if not node.add_external_address(ADDR):
                print("FAIL: advertised add returned False")
                return 1
            if not store.is_file():
                print("FAIL: nested dest missing after persist")
                return 1
            if tmp.exists():
                print(f"FAIL: tmp leftover: {tmp}")
                return 1
            disk = json.loads(store.read_text(encoding="utf-8"))
            if ADDR not in list(disk.get("addrs") or []):
                print(f"FAIL: dest missing advertised: {disk}")
                return 1
            print(f"OK: mkdir fsync nested={nested} strategy={want}")
        finally:
            try:
                node.close()
            except Exception:
                pass

    print("OK: libp2p_rust_persist_mkdir_fsync_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; mkdir ancestor fsync after create_dir_all; "
        "not POSIX inode-atomic on NTFS; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
