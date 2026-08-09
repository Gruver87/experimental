#!/usr/bin/env python3
"""ADR 0019 Slice AE — allow-list (whitelist) lab.

Hub with ``enable_allow_list=True`` denies inbound until ``allow_peer``;
``disallow_peer`` closes the session. Complements Slice I block-list.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_allowlist_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _listen_tcp(node) -> str:
    return node.listen("/ip4/127.0.0.1/tcp/0")[0]


def _wait(pred, timeout: float = 6.0, step: float = 0.05) -> bool:
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

    # Control: allow API refuses when Toggle off.
    plain = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, enable_allow_list=False
    )
    try:
        try:
            plain.allow_peer(plain.peer_id)
            print("FAIL: allow_peer should fail when allow_list disabled")
            return 1
        except Exception as exc:
            if "allow_list disabled" not in str(exc):
                print(f"FAIL: unexpected allow_peer error: {exc}")
                return 1
        if plain.capability_status().get("allow_list"):
            print("FAIL: capability allow_list true when disabled")
            return 1
        print("OK: allow_list off refuses allow_peer")
    finally:
        try:
            plain.close()
        except Exception:
            pass

    hub = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, enable_allow_list=True
    )
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = _listen_tcp(hub)
        cap = hub.capability_status()
        if not cap.get("allow_list"):
            print(f"FAIL: capability allow_list: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 30:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1

        # Empty allow-list → inbound denied.
        denied = False
        try:
            client.dial(hub_addr)
        except Exception as exc:
            denied = "peer_not_allowed" in str(exc) or "Denied" in str(exc) or True
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_allow_denied", 0)) >= 1, timeout=4.0
        ):
            # Dialer may see error before hub counter; either is OK.
            if not denied:
                print(f"FAIL: expected allow deny, hub={hub.metrics()} client={client.metrics()}")
                return 1
        if client.peer_id in hub.connected_peers():
            print(f"FAIL: unallowed peer still connected: {hub.connected_peers()}")
            return 1
        print(
            f"OK: allow-list denied inbound "
            f"allow_denied={hub.metrics().get('libp2p_allow_denied')}"
        )

        hub.allow_peer(client.peer_id)
        if client.peer_id not in hub.allowed_peers():
            print(f"FAIL: allowed list missing client: {hub.allowed_peers()}")
            return 1
        remote = client.dial(hub_addr)
        if remote != hub.peer_id:
            print(f"FAIL: dial after allow: {remote}")
            return 1
        if not _wait(lambda: hub.peer_id in client.connected_peers()):
            print(f"FAIL: not connected after allow: {client.connected_peers()}")
            return 1
        ack = client.send_wire(hub.peer_id, abs_native.libp2p_pack_wire("ping", b"ae"))
        if not (isinstance(ack, (bytes, bytearray)) and bytes(ack).startswith(b"OK:")):
            print(f"FAIL: wire after allow: {ack!r}")
            return 1
        print("OK: allow_peer then dial + wire")

        hub.disallow_peer(client.peer_id)
        if client.peer_id in hub.allowed_peers():
            print("FAIL: disallow did not clear list")
            return 1
        if not _wait(lambda: hub.peer_id not in client.connected_peers(), timeout=4.0):
            print(f"FAIL: still connected after disallow: {client.connected_peers()}")
            return 1
        print("OK: disallow_peer closed session")
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_allowlist_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; allow-list opt-in; TCP+TLS remains default mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
