#!/usr/bin/env python3
"""ADR 0019 Slice BE — peerstore_remove (forget peer) lab.

Learn hub via dial/identify into ``peerstore_path``, then ``peerstore_remove``
drops the entry (memory + disk) and bumps ``peerstore_removed``.
Capability ``peerstore_remove`` / phase >= 56.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_peerstore_remove_lab.py
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


def _wait(pred, timeout: float = 8.0, step: float = 0.05) -> bool:
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

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-peerstore-rm-") as td:
        store_path = str(Path(td) / "peerstore.json")
        hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        client = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            peerstore_path=store_path,
        )
        try:
            hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
            client.listen("/ip4/127.0.0.1/tcp/0")
            remote = client.dial(hub_addr)
            if remote != hub.peer_id:
                print(f"FAIL: dial remote {remote}")
                return 1

            if not _wait(
                lambda: hub.peer_id in dict(client.peerstore_list()),
                timeout=8.0,
            ):
                print(
                    f"FAIL: peerstore not learned "
                    f"list={dict(client.peerstore_list())} "
                    f"metrics={client.metrics()}"
                )
                return 1

            before = int(client.metrics().get("libp2p_peerstore_removed", 0))
            removed = client.peerstore_remove(hub.peer_id)
            if not removed:
                print("FAIL: peerstore_remove returned False")
                return 1
            if hub.peer_id in dict(client.peerstore_list()):
                print(f"FAIL: still listed: {dict(client.peerstore_list())}")
                return 1
            if int(client.metrics().get("libp2p_peerstore_removed", 0)) <= before:
                print(f"FAIL: removed counter: {client.metrics()}")
                return 1

            disk = json.loads(Path(store_path).read_text(encoding="utf-8"))
            if hub.peer_id in (disk.get("peers") or {}):
                print(f"FAIL: disk still has hub: {disk}")
                return 1

            # Idempotent miss.
            if client.peerstore_remove(hub.peer_id):
                print("FAIL: second remove should be False")
                return 1

            m = client.metrics()
            cap = client.capability_status()
            print(
                f"OK: peerstore_removed={m.get('libp2p_peerstore_removed')} "
                f"peers={m.get('libp2p_peerstore_peers')}"
            )
            if not cap.get("peerstore_remove"):
                print(f"FAIL: capability peerstore_remove: {cap}")
                return 1
            if not cap.get("peerstore"):
                print(f"FAIL: capability peerstore: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 56:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
        finally:
            for n in (client, hub):
                try:
                    n.close()
                except Exception:
                    pass

    print("OK: libp2p_rust_peerstore_remove_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; peerstore remove; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
