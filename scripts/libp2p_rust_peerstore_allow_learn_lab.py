#!/usr/bin/env python3
"""ADR 0019 Slice BF — peerstore_allow_learn lab.

After ``peerstore_remove``, forget blocks re-learn. ``peerstore_allow_learn``
clears forget; an identify push re-populates the book.
Capability ``peerstore_allow_learn`` / phase >= 57.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_peerstore_allow_learn_lab.py
"""

from __future__ import annotations

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

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-peerstore-al-") as td:
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
            client.dial(hub_addr)
            if not _wait(
                lambda: hub.peer_id in dict(client.peerstore_list())
                and int(client.metrics().get("libp2p_identify_received", 0)) >= 1,
                timeout=8.0,
            ):
                print(
                    f"FAIL: initial learn "
                    f"list={dict(client.peerstore_list())} m={client.metrics()}"
                )
                return 1

            if not client.peerstore_remove(hub.peer_id):
                print("FAIL: peerstore_remove")
                return 1
            if hub.peer_id in dict(client.peerstore_list()):
                print("FAIL: still listed after remove")
                return 1

            # Forget must hold while still connected (identify noise).
            time.sleep(0.4)
            if hub.peer_id in dict(client.peerstore_list()):
                print("FAIL: re-learned while forgotten")
                return 1

            before_al = int(client.metrics().get("libp2p_peerstore_allow_learn", 0))
            before_learned = int(client.metrics().get("libp2p_peerstore_learned", 0))
            if not client.peerstore_allow_learn(hub.peer_id):
                print("FAIL: peerstore_allow_learn returned False")
                return 1
            if int(client.metrics().get("libp2p_peerstore_allow_learn", 0)) <= before_al:
                print(f"FAIL: allow_learn counter: {client.metrics()}")
                return 1
            # Idempotent miss.
            if client.peerstore_allow_learn(hub.peer_id):
                print("FAIL: second allow_learn should be False")
                return 1

            # Trigger re-learn via identify push from hub → client Received.
            hub.identify_push(client.peer_id)
            if not _wait(
                lambda: hub.peer_id in dict(client.peerstore_list())
                and int(client.metrics().get("libp2p_peerstore_learned", 0))
                > before_learned,
                timeout=5.0,
            ):
                print(
                    f"FAIL: no re-learn after allow "
                    f"list={dict(client.peerstore_list())} m={client.metrics()}"
                )
                return 1

            m = client.metrics()
            cap = client.capability_status()
            print(
                f"OK: allow_learn={m.get('libp2p_peerstore_allow_learn')} "
                f"removed={m.get('libp2p_peerstore_removed')} "
                f"learned={m.get('libp2p_peerstore_learned')} "
                f"peers={m.get('libp2p_peerstore_peers')}"
            )
            if not cap.get("peerstore_allow_learn"):
                print(f"FAIL: capability peerstore_allow_learn: {cap}")
                return 1
            if not cap.get("peerstore_remove"):
                print(f"FAIL: capability peerstore_remove: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 57:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
        finally:
            for n in (client, hub):
                try:
                    n.close()
                except Exception:
                    pass

    print("OK: libp2p_rust_peerstore_allow_learn_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; peerstore allow-learn; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
