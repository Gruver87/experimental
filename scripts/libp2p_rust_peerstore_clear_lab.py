#!/usr/bin/env python3
"""ADR 0019 Slice BK — peerstore_clear lab.

``peerstore_clear`` wipes the learned peerstore, persists the empty set,
returns the number of peers cleared, bumps ``peerstore_cleared``, and
forgets cleared peers so identify cannot re-learn while still connected.
Capability ``peerstore_clear`` / phase >= 62.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_peerstore_clear_lab.py
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


def _wait(pred, timeout: float = 10.0, step: float = 0.05) -> bool:
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

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-peerstore-clr-") as td:
        store_path = str(Path(td) / "peerstore.json")
        hub_a = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        hub_b = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        client = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            peerstore_path=store_path,
        )
        try:
            addr_a = hub_a.listen("/ip4/127.0.0.1/tcp/0")[0]
            addr_b = hub_b.listen("/ip4/127.0.0.1/tcp/0")[0]
            client.listen("/ip4/127.0.0.1/tcp/0")
            client.dial(addr_a)
            client.dial(addr_b)
            if not _wait(
                lambda: hub_a.peer_id in dict(client.peerstore_list())
                and hub_b.peer_id in dict(client.peerstore_list()),
                timeout=10.0,
            ):
                print(
                    f"FAIL: peerstore not learned "
                    f"list={dict(client.peerstore_list())} m={client.metrics()}"
                )
                return 1
            disk = json.loads(Path(store_path).read_text(encoding="utf-8"))
            if len(disk.get("peers") or {}) < 2:
                print(f"FAIL: disk peers < 2: {disk}")
                return 1

            before = int(client.metrics().get("libp2p_peerstore_cleared", 0))
            cleared = client.peerstore_clear()
            if cleared != 2:
                print(f"FAIL: peerstore_clear returned {cleared}, want 2")
                return 1
            if dict(client.peerstore_list()):
                print(f"FAIL: still listed: {dict(client.peerstore_list())}")
                return 1
            if int(client.metrics().get("libp2p_peerstore_cleared", 0)) != before + 2:
                print(f"FAIL: cleared counter: {client.metrics()}")
                return 1
            disk2 = json.loads(Path(store_path).read_text(encoding="utf-8"))
            if disk2.get("peers"):
                print(f"FAIL: disk still has peers: {disk2}")
                return 1
            if client.peerstore_clear() != 0:
                print("FAIL: second clear should return 0")
                return 1

            m = client.metrics()
            cap = client.capability_status()
            print(
                f"OK: peerstore_cleared={m.get('libp2p_peerstore_cleared')} "
                f"peers={len(dict(client.peerstore_list()))}"
            )
            if not cap.get("peerstore_clear"):
                print(f"FAIL: capability peerstore_clear: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 62:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
        finally:
            for n in (client, hub_a, hub_b):
                try:
                    n.close()
                except Exception:
                    pass

    print("OK: libp2p_rust_peerstore_clear_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; peerstore clear; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
