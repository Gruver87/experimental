#!/usr/bin/env python3
"""libp2p Identify + DualStackDialer discovery lab (ADR 0018 wave-8).

Identify encoding stays in-process. Dual-stack dial_discovered:
  - stub wheel: dials registry multiaddr as phase-1 handle
  - rust wheel: in-process fake port must fail-closed; real listen+announce OK

Usage:
  python scripts/libp2p_identify_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.transport.dual_stack import DualStackDialer
from network.transport.errors import TransportCapabilityError
from network.transport.libp2p_adapter import DiscoveryRegistry, InProcessSwarm
from network.transport.libp2p_adapter.identify import IdentifyService


def main() -> int:
    swarm = InProcessSwarm()
    a = swarm.spawn("n1", "/ip4/127.0.0.1/tcp/4501/p2p/n1")
    b = swarm.spawn("n2", "/ip4/127.0.0.1/tcp/4502/p2p/n2")
    a.dial(b.listen.to_string())

    id_a = IdentifyService(a)
    id_b = IdentifyService(b)
    info = id_a.identify("n2")
    assert info.peer_id == "n2"
    assert any("4502" in x for x in info.listen_addrs)
    _ = id_b  # registered for symmetry / future push labs

    reg = DiscoveryRegistry()
    reg.announce("n2", b.listen.to_string())
    dialer = DualStackDialer(feature_libp2p=True)
    try:
        if dialer.libp2p.rust_backend:
            # Fake in-process port must not look like a successful rust dial.
            try:
                dialer.dial_discovered(reg, "n2")
                print("FAIL: expected fail-closed dial to in-process stub addr")
                return 1
            except TransportCapabilityError:
                pass

            import abs_native

            listener = abs_native.libp2p_node_new(
                enable_mdns=False, enable_reconnect=False
            )
            try:
                listen = listener.listen("/ip4/127.0.0.1/tcp/0")[0]
                ma = f"{listen}/p2p/{listener.peer_id}"
                reg_rust = DiscoveryRegistry()
                reg_rust.announce(listener.peer_id, ma)
                h = dialer.dial_discovered(reg_rust, listener.peer_id)
                if h.get("kind") != "libp2p":
                    print(f"FAIL: kind={h}")
                    return 1
                if not h.get("handle", {}).get("connected"):
                    print(f"FAIL: not connected: {h}")
                    return 1
                print(
                    f"OK: rust dial_discovered peer={h['handle'].get('peer_id')} "
                    f"backend={h['handle'].get('backend')}"
                )
            finally:
                try:
                    listener.close()
                except Exception:
                    pass
        else:
            h = dialer.dial_discovered(reg, "n2")
            if h.get("kind") != "libp2p":
                print(f"FAIL: kind={h}")
                return 1
            if h.get("handle", {}).get("peer_id") != "n2":
                print(f"FAIL: peer_id={h}")
                return 1
            print("OK: stub dial_discovered peer=n2")
    finally:
        dialer.libp2p.close()

    print("OK: libp2p_identify_lab PASS")
    print("  identify: /ipfs/id/1.0.0 lab encoding")
    print("  dual-stack: dial_discovered via registry")
    print("  honesty: in-process identify; not rust identify protobuf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
