#!/usr/bin/env python3
"""ADR 0019 Slice L — wire timeout + adapter API parity lab.

- Custom wire_timeout_secs surfaces in metrics
- Adapter exposes listen/kad/block + status_snapshot
- Dual-stack dial still works with FEATURE_LIBP2P

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_wire_timeout_lab.py
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

    from network.transport.dual_stack import DualStackDialer
    from network.transport.libp2p_adapter import Libp2pTransportAdapter
    from network.transport.types import PeerEndpoint

    # Native timeout config
    n = abs_native.libp2p_node_new(wire_timeout_secs=7, enable_mdns=False)
    try:
        m = n.metrics()
        if int(m.get("libp2p_wire_timeout_secs", 0)) != 7:
            print(f"FAIL: wire_timeout_secs metric: {m}")
            return 1
        cap = n.capability_status()
        if int(cap.get("wire_timeout_secs", 0)) != 7:
            print(f"FAIL: capability wire_timeout: {cap}")
            return 1
        print("OK: wire_timeout_secs=7 configured")
    finally:
        n.close()

    # Adapter parity: listen + dial + kad + block + snapshot
    hub = abs_native.libp2p_node_new(enable_mdns=False, wire_timeout_secs=5)
    ad = Libp2pTransportAdapter(
        enabled=True,
        enable_mdns=False,
        wire_timeout_secs=5,
    )
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        port = int(hub_addr.rsplit("/", 1)[-1])
        listens = ad.listen("/ip4/127.0.0.1/tcp/0")
        if not listens:
            print("FAIL: adapter.listen empty")
            return 1
        ds = DualStackDialer(feature_libp2p=True, libp2p=ad)
        handle = ds.dial(PeerEndpoint(host="127.0.0.1", port=port))
        if handle.get("kind") != "libp2p":
            print(f"FAIL: dual-stack kind: {handle}")
            return 1
        time.sleep(0.25)
        ad.kad_add_address(hub.peer_id, hub_addr)
        closest = ad.kad_get_closest_peers(hub.peer_id)
        if not isinstance(closest, list):
            print(f"FAIL: kad_get_closest not list: {closest!r}")
            return 1
        other = abs_native.libp2p_node_new(enable_mdns=False)
        try:
            ad.block_peer(other.peer_id)
            if other.peer_id not in ad.blocked_peers():
                print("FAIL: adapter.block_peer")
                return 1
        finally:
            other.close()
        snap = dict(ad.status_snapshot())
        if int(snap.get("libp2p_wire_timeout_secs", 0)) != 5:
            print(f"FAIL: snapshot wire timeout: {snap}")
            return 1
        if snap.get("default_mesh") is not False:
            print("FAIL: default_mesh must be False")
            return 1
        print("OK: adapter parity (listen/kad/block/snapshot)")
        print(f"  wire_timeout_secs={snap.get('libp2p_wire_timeout_secs')}")
        print(f"  closest_len={len(closest)} peers={snap.get('libp2p_peers')}")
    finally:
        try:
            ad.close()
        except Exception:
            pass
        try:
            hub.close()
        except Exception:
            pass

    print("OK: libp2p_rust_wire_timeout_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; not prod mesh; not tip proof")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
