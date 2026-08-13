#!/usr/bin/env python3
"""ADR 0019 Slice BQ — atomic persist of advertised externals.

Persist writes a same-dir ``*.tmp``, fsyncs, then renames onto the dest.
The destination is never truncated in place. A leftover tmp from a crash
is overwritten and removed. Capability ``external_addrs_atomic_persist``
/ phase >= 68.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_external_addrs_atomic_persist_lab.py
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

ADVERTISED = "/ip4/203.0.113.68/tcp/4068"
REPLACED = "/ip4/203.0.113.69/tcp/4069"


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

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-extatomic-") as td:
        store = Path(td) / "external_addrs.json"
        tmp = Path(str(store) + ".tmp")
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            external_addrs_path=str(store),
        )
        try:
            addrs = node.listen("/ip4/127.0.0.1/tcp/0")
            if not addrs:
                print("FAIL: empty listen")
                return 1
            if not _wait(lambda: addrs[0] in node.external_addrs(), timeout=4.0):
                print(f"FAIL: listen not external: {node.external_addrs()}")
                return 1

            if not node.add_external_address(ADVERTISED):
                print("FAIL: first advertised add returned False")
                return 1
            if not store.is_file():
                print("FAIL: dest missing after persist")
                return 1
            if tmp.exists():
                print(f"FAIL: tmp leftover after persist: {tmp}")
                return 1
            disk = json.loads(store.read_text(encoding="utf-8"))
            if ADVERTISED not in list(disk.get("addrs") or []):
                print(f"FAIL: dest missing advertised: {disk}")
                return 1

            tmp.write_text("{stale", encoding="utf-8")
            if not node.add_external_address(REPLACED):
                print("FAIL: second advertised add returned False")
                return 1
            if tmp.exists():
                print("FAIL: stale tmp not cleaned")
                return 1
            disk2 = json.loads(store.read_text(encoding="utf-8"))
            got = list(disk2.get("addrs") or [])
            if ADVERTISED not in got or REPLACED not in got:
                print(f"FAIL: dest after replace: {disk2}")
                return 1

            cap = node.capability_status()
            if not cap.get("external_addrs_atomic_persist"):
                print(f"FAIL: capability atomic persist: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 68:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            print(f"OK: atomic persist dest={got} tmp_gone=True")
        finally:
            try:
                node.close()
            except Exception:
                pass

    print("OK: libp2p_rust_external_addrs_atomic_persist_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; atomic persist advertised externals; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
