#!/usr/bin/env python3
"""ADR 0019 Slice BH — bootstrap_remove lab.

``bootstrap_remove`` returns True when the peer was present, persists the
drop, and bumps ``bootstrap_removed``. Capability ``bootstrap_remove`` /
phase >= 59.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_bootstrap_remove_lab.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-boot-rm-") as td:
        boot_path = str(Path(td) / "bootstrap.json")
        hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            bootstrap_path=boot_path,
        )
        try:
            hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
            hub_ma = f"{hub_addr}/p2p/{hub.peer_id}"
            node.listen("/ip4/127.0.0.1/tcp/0")
            node.bootstrap_add(hub.peer_id, hub_ma)
            listed = dict(node.bootstrap_list())
            if hub.peer_id not in listed:
                print(f"FAIL: bootstrap_list missing hub: {listed}")
                return 1
            disk = json.loads(Path(boot_path).read_text(encoding="utf-8"))
            if hub.peer_id not in (disk.get("peers") or {}):
                print(f"FAIL: disk missing hub: {disk}")
                return 1

            before = int(node.metrics().get("libp2p_bootstrap_removed", 0))
            removed = node.bootstrap_remove(hub.peer_id)
            if not removed:
                print("FAIL: bootstrap_remove returned False")
                return 1
            if hub.peer_id in dict(node.bootstrap_list()):
                print(f"FAIL: still listed: {dict(node.bootstrap_list())}")
                return 1
            if int(node.metrics().get("libp2p_bootstrap_removed", 0)) <= before:
                print(f"FAIL: removed counter: {node.metrics()}")
                return 1
            disk2 = json.loads(Path(boot_path).read_text(encoding="utf-8"))
            if hub.peer_id in (disk2.get("peers") or {}):
                print(f"FAIL: disk still has hub: {disk2}")
                return 1
            if node.bootstrap_remove(hub.peer_id):
                print("FAIL: second remove should be False")
                return 1

            m = node.metrics()
            cap = node.capability_status()
            print(
                f"OK: bootstrap_removed={m.get('libp2p_bootstrap_removed')} "
                f"peers={m.get('libp2p_bootstrap_peers')}"
            )
            if not cap.get("bootstrap_remove"):
                print(f"FAIL: capability bootstrap_remove: {cap}")
                return 1
            if not cap.get("bootstrap"):
                print(f"FAIL: capability bootstrap: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 59:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
        finally:
            for n in (node, hub):
                try:
                    n.close()
                except Exception:
                    pass

    print("OK: libp2p_rust_bootstrap_remove_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; bootstrap remove; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
