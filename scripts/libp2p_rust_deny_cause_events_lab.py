#!/usr/bin/env python3
"""ADR 0019 Slice AX — Denied cause taxonomy (block / allow / limit).

1) Outbound block → ``dial_fail_denied_block``.
2) Inbound empty allow-list → ``incoming_fail_denied_allow``.
3) Outbound connection-limit → ``dial_fail_denied_limit``.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_deny_cause_events_lab.py
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

    # Part 1: outbound block cause.
    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        hub_ma = f"{hub_addr}/p2p/{hub.peer_id}"
        client.block_peer(hub.peer_id)
        before = int(client.metrics().get("libp2p_dial_fail_denied_block", 0))
        try:
            client.dial(hub_ma)
        except Exception as exc:
            print(f"  block dial note: {exc}")
        if not _wait(
            lambda: int(client.metrics().get("libp2p_dial_fail_denied_block", 0))
            > before,
            timeout=4.0,
        ):
            print(f"FAIL: dial_fail_denied_block client={client.metrics()}")
            return 1
        print(
            f"OK: dial_fail_denied_block="
            f"{client.metrics().get('libp2p_dial_fail_denied_block')}"
        )
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    # Part 2: inbound allow-list cause.
    hub = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, enable_allow_list=True
    )
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        before = int(hub.metrics().get("libp2p_incoming_fail_denied_allow", 0))
        try:
            client.dial(hub_addr)
        except Exception as exc:
            print(f"  allow dial note: {exc}")
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_incoming_fail_denied_allow", 0))
            > before,
            timeout=4.0,
        ):
            print(f"FAIL: incoming_fail_denied_allow hub={hub.metrics()}")
            return 1
        print(
            f"OK: incoming_fail_denied_allow="
            f"{hub.metrics().get('libp2p_incoming_fail_denied_allow')}"
        )
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    # Part 3: outbound connection-limit cause.
    hub_a = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    hub_b = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    dialer = abs_native.libp2p_node_new(
        enable_mdns=False,
        enable_reconnect=False,
        max_established_outgoing=1,
    )
    try:
        a_addr = hub_a.listen("/ip4/127.0.0.1/tcp/0")[0]
        b_addr = hub_b.listen("/ip4/127.0.0.1/tcp/0")[0]
        dialer.dial(a_addr)
        if not _wait(
            lambda: hub_a.peer_id in dialer.connected_peers(),
            timeout=4.0,
        ):
            print(f"FAIL: first dial did not connect: {dialer.metrics()}")
            return 1
        before = int(dialer.metrics().get("libp2p_dial_fail_denied_limit", 0))
        try:
            dialer.dial(b_addr)
        except Exception as exc:
            print(f"  limit dial note: {exc}")
        if not _wait(
            lambda: int(dialer.metrics().get("libp2p_dial_fail_denied_limit", 0))
            > before,
            timeout=4.0,
        ):
            print(f"FAIL: dial_fail_denied_limit dialer={dialer.metrics()}")
            return 1
        print(
            f"OK: dial_fail_denied_limit="
            f"{dialer.metrics().get('libp2p_dial_fail_denied_limit')}"
        )

        cap = dialer.capability_status()
        if not cap.get("deny_cause_events"):
            print(f"FAIL: capability deny_cause_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 49:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (dialer, hub_a, hub_b):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_deny_cause_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; deny cause events; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
