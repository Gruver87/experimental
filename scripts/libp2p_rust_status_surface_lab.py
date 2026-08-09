#!/usr/bin/env python3
"""ADR 0019 Slice J — status surface lab.

Proves adapter.status_snapshot / shared metric keys expose dial + block counters
after a real rust dial and block_peer.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_status_surface_lab.py
"""

from __future__ import annotations

import sys
import time
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

    from network.transport.libp2p_adapter import (
        LIBP2P_STATUS_METRIC_KEYS,
        Libp2pPeerPolicy,
        Libp2pTransportAdapter,
    )
    from network.transport.types import PeerEndpoint

    hub = abs_native.libp2p_node_new()
    policy = Libp2pPeerPolicy()
    ad = Libp2pTransportAdapter(enabled=True, peer_policy=policy)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        # parse port from /ip4/127.0.0.1/tcp/PORT
        port = int(hub_addr.rsplit("/", 1)[-1])
        handle = ad.connect(PeerEndpoint(host="127.0.0.1", port=port))
        if not handle.get("connected"):
            print(f"FAIL: dial not connected: {handle}")
            return 1
        time.sleep(0.25)

        snap = dict(ad.status_snapshot())
        for key in LIBP2P_STATUS_METRIC_KEYS:
            if key not in snap:
                print(f"FAIL: missing status key {key}")
                return 1
        if int(snap.get("libp2p_dial_ok", 0)) < 1 and int(snap.get("libp2p_peers", 0)) < 1:
            print(f"FAIL: expected dial/peers in snapshot: {snap}")
            return 1
        if snap.get("default_mesh") is not False:
            print("FAIL: default_mesh must stay False")
            return 1
        if "ADR0019" not in str(snap.get("honesty", "")):
            print(f"FAIL: honesty missing: {snap.get('honesty')}")
            return 1

        # Block path should surface libp2p_block_denied / blocked_peers via adapter
        other = abs_native.libp2p_node_new()
        try:
            ad.block_peer(other.peer_id)
            if other.peer_id not in ad.blocked_peers():
                print(f"FAIL: blocked_peers missing {other.peer_id}")
                return 1
            snap2 = dict(ad.status_snapshot())
            if int(snap2.get("libp2p_blocked_peers", 0)) < 1:
                print(f"FAIL: blocked_peers metric: {snap2}")
                return 1
            # policy should have been attach_native'd on ensure_node
            pst = policy.status()
            if not pst.get("native_attached"):
                print(f"FAIL: policy not attached to native: {pst}")
                return 1
        finally:
            other.close()

        print("OK: libp2p_rust_status_surface_lab PASS")
        print(f"  dial_ok={snap.get('libp2p_dial_ok')} peers={snap.get('libp2p_peers')}")
        print(f"  blocked_peers={snap2.get('libp2p_blocked_peers')}")
        print(f"  keys={len(LIBP2P_STATUS_METRIC_KEYS)}")
        print("  honesty: FEATURE_LIBP2P lab status surface; not prod mesh")
        return 0
    finally:
        try:
            ad.close()
        except Exception:
            pass
        try:
            hub.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
