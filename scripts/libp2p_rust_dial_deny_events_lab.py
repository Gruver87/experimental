#!/usr/bin/env python3
"""ADR 0019 Slice AW — outbound DialError::Denied taxonomy lab.

Client blocks hub → dial → ``dial_fail_denied`` + ``block_denied``.
Capability ``dial_deny_events`` / phase >= 48.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_dial_deny_events_lab.py
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

        client.block_peer(hub.peer_id)
        if hub.peer_id not in client.blocked_peers():
            print(f"FAIL: block did not stick: {client.blocked_peers()}")
            return 1

        before_denied = int(client.metrics().get("libp2p_dial_fail_denied", 0))
        before_block = int(client.metrics().get("libp2p_block_denied", 0))
        try:
            client.dial(hub_ma)
        except Exception as exc:
            print(f"  dial note: {exc}")

        if not _wait(
            lambda: int(client.metrics().get("libp2p_dial_fail_denied", 0))
            > before_denied
            and int(client.metrics().get("libp2p_block_denied", 0)) > before_block,
            timeout=4.0,
        ):
            print(f"FAIL: dial_fail_denied client={client.metrics()}")
            return 1

        cm = client.metrics()
        print(
            f"OK: dial_fail_denied={cm.get('libp2p_dial_fail_denied')} "
            f"block_denied={cm.get('libp2p_block_denied')} "
            f"dial_fail={cm.get('libp2p_dial_fail')}"
        )

        cap = client.capability_status()
        if not cap.get("dial_deny_events"):
            print(f"FAIL: capability dial_deny_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 48:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_dial_deny_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; dial deny events; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
