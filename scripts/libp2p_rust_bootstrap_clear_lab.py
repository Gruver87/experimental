#!/usr/bin/env python3
"""ADR 0019 Slice BJ — bootstrap_clear lab.

``bootstrap_clear`` wipes the bootstrap book, persists the empty set, returns
the number of peers cleared, and bumps ``bootstrap_cleared``. Capability
``bootstrap_clear`` / phase >= 61.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_bootstrap_clear_lab.py
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

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-boot-clr-") as td:
        boot_path = str(Path(td) / "bootstrap.json")
        hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        peer_b = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            bootstrap_path=boot_path,
        )
        try:
            hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
            peer_b_addr = peer_b.listen("/ip4/127.0.0.1/tcp/0")[0]
            hub_ma = f"{hub_addr}/p2p/{hub.peer_id}"
            peer_b_ma = f"{peer_b_addr}/p2p/{peer_b.peer_id}"
            node.listen("/ip4/127.0.0.1/tcp/0")
            node.bootstrap_add(hub.peer_id, hub_ma)
            node.bootstrap_add(peer_b.peer_id, peer_b_ma)
            listed = dict(node.bootstrap_list())
            if len(listed) != 2:
                print(f"FAIL: expected 2 bootstrap peers: {listed}")
                return 1
            disk = json.loads(Path(boot_path).read_text(encoding="utf-8"))
            if len(disk.get("peers") or {}) != 2:
                print(f"FAIL: disk peers != 2: {disk}")
                return 1

            before = int(node.metrics().get("libp2p_bootstrap_cleared", 0))
            cleared = node.bootstrap_clear()
            if cleared != 2:
                print(f"FAIL: bootstrap_clear returned {cleared}, want 2")
                return 1
            if dict(node.bootstrap_list()):
                print(f"FAIL: still listed: {dict(node.bootstrap_list())}")
                return 1
            if int(node.metrics().get("libp2p_bootstrap_peers", -1)) != 0:
                print(f"FAIL: bootstrap_peers metric: {node.metrics()}")
                return 1
            if int(node.metrics().get("libp2p_bootstrap_cleared", 0)) != before + 2:
                print(f"FAIL: cleared counter: {node.metrics()}")
                return 1
            disk2 = json.loads(Path(boot_path).read_text(encoding="utf-8"))
            if disk2.get("peers"):
                print(f"FAIL: disk still has peers: {disk2}")
                return 1
            if node.bootstrap_clear() != 0:
                print("FAIL: second clear should return 0")
                return 1

            m = node.metrics()
            cap = node.capability_status()
            print(
                f"OK: bootstrap_cleared={m.get('libp2p_bootstrap_cleared')} "
                f"peers={m.get('libp2p_bootstrap_peers')}"
            )
            if not cap.get("bootstrap_clear"):
                print(f"FAIL: capability bootstrap_clear: {cap}")
                return 1
            if not cap.get("bootstrap"):
                print(f"FAIL: capability bootstrap: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 61:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
        finally:
            for n in (node, hub, peer_b):
                try:
                    n.close()
                except Exception:
                    pass

    print("OK: libp2p_rust_bootstrap_clear_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; bootstrap clear; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
