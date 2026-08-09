#!/usr/bin/env python3
"""ADR 0019 Slice AV — inbound ListenError taxonomy lab.

Hub blocks client → inbound Denied → ``incoming_fail_denied`` +
``incoming_connection_error``. Capability ``incoming_fail_events``.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_incoming_fail_events_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        hub_ma = f"{hub_addr}/p2p/{hub.peer_id}"

        hub.block_peer(client.peer_id)
        if client.peer_id not in hub.blocked_peers():
            print(f"FAIL: block did not stick: {hub.blocked_peers()}")
            return 1

        before_denied = int(hub.metrics().get("libp2p_incoming_fail_denied", 0))
        before_total = int(hub.metrics().get("libp2p_incoming_connection_error", 0))
        try:
            client.dial(hub_ma)
        except Exception as exc:
            print(f"  dial note: {exc}")

        if not _wait(
            lambda: int(hub.metrics().get("libp2p_incoming_fail_denied", 0))
            > before_denied
            and int(hub.metrics().get("libp2p_incoming_connection_error", 0))
            > before_total,
            timeout=4.0,
        ):
            print(f"FAIL: incoming_fail_denied hub={hub.metrics()}")
            return 1

        hm = hub.metrics()
        if int(hm.get("libp2p_block_denied", 0)) < 1:
            print(f"FAIL: expected block_denied hub={hm}")
            return 1
        print(
            f"OK: denied={hm.get('libp2p_incoming_fail_denied')} "
            f"incoming_error={hm.get('libp2p_incoming_connection_error')} "
            f"block_denied={hm.get('libp2p_block_denied')}"
        )

        cap = hub.capability_status()
        if not cap.get("incoming_fail_events"):
            print(f"FAIL: capability incoming_fail_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 47:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_incoming_fail_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; incoming fail events; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
