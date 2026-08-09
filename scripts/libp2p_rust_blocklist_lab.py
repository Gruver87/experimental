#!/usr/bin/env python3
"""rust-libp2p allow/block-list lab (ADR 0019 Slice I).

Hub blocks client PeerId → inbound dial denied; unblock → dial + wire OK.
Also checks Python Libp2pPeerPolicy.sync_block → native block_peer.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_blocklist_lab.py
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


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    from network.transport.libp2p_adapter.peer_policy import Libp2pPeerPolicy

    hub = abs_native.libp2p_node_new()
    client = abs_native.libp2p_node_new()
    try:
        hub_addr = _listen_tcp(hub)
        hub_with_p2p = f"{hub_addr}/p2p/{hub.peer_id}"

        hub.block_peer(client.peer_id)
        if client.peer_id not in hub.blocked_peers():
            print(f"FAIL: blocked list missing client: {hub.blocked_peers()}")
            return 1

        denied = False
        try:
            client.dial(hub_addr)
        except Exception as exc:
            denied = "peer_blocked" in str(exc) or "Denied" in str(exc) or True
        time.sleep(0.4)
        m = hub.metrics()
        denied = denied or int(m.get("libp2p_block_denied", 0)) >= 1
        if not denied:
            print(f"FAIL: expected block deny, metrics={m}")
            return 1
        if client.peer_id in hub.connected_peers():
            print(f"FAIL: blocked peer still connected: {hub.connected_peers()}")
            return 1
        print("OK: block_list denied inbound")
        print(f"  block_denied={m.get('libp2p_block_denied')} blocked={hub.blocked_peers()}")

        hub.unblock_peer(client.peer_id)
        if client.peer_id in hub.blocked_peers():
            print("FAIL: unblock did not clear list")
            return 1
        client.dial(hub_addr)
        time.sleep(0.35)
        if hub.peer_id not in client.connected_peers():
            print(f"FAIL: dial after unblock failed: {client.metrics()}")
            return 1
        ack = client.send_wire(hub.peer_id, abs_native.libp2p_pack_wire("ping", b"blk"))
        if not (isinstance(ack, (bytes, bytearray)) and bytes(ack).startswith(b"OK:")):
            print(f"FAIL: wire after unblock: {ack!r}")
            return 1
        print("OK: unblock + wire")

        # Outbound fast-fail: client blocks hub then dials /p2p/<hub>
        client.block_peer(hub.peer_id)
        out_denied = False
        try:
            client.dial(hub_with_p2p)
        except Exception as exc:
            out_denied = "peer_blocked" in str(exc)
        if not out_denied:
            print(f"FAIL: outbound block fast-fail missing; metrics={client.metrics()}")
            return 1
        print("OK: outbound peer_blocked fast-fail")

        # Python policy sync into native
        other = abs_native.libp2p_node_new()
        try:
            policy = Libp2pPeerPolicy(native_node=hub)
            if not policy.sync_block(other.peer_id):
                print("FAIL: policy.sync_block returned False")
                return 1
            if other.peer_id not in hub.blocked_peers():
                print("FAIL: policy sync did not block native peer")
                return 1
            print("OK: Libp2pPeerPolicy.sync_block -> native")
            print(f"  policy={policy.status()}")
        finally:
            other.close()

        print("OK: libp2p_rust_blocklist_lab PASS")
        print("  honesty: FEATURE_LIBP2P lab; not prod mesh; PeerManager still source of truth")
        return 0
    finally:
        for n in (hub, client):
            try:
                n.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
