#!/usr/bin/env python3
"""ADR 0019 Slice W — IPv6 dual-stack listen/dial lab.

Listen and dial on ``/ip6/::1/tcp/0``; also confirm multiaddr parse + adapter
dial builds ``/ip6/...`` for IPv6 hosts.

Requires abs_native built with Cargo feature ``libp2p`` and OS IPv6 loopback.

Usage:
  python scripts/libp2p_rust_ipv6_lab.py
"""

from __future__ import annotations

import sys
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

    from network.transport.libp2p_adapter.multiaddr import Multiaddr, parse_multiaddr

    ma = parse_multiaddr("/ip6/::1/tcp/4401/p2p/lab-w")
    if ma.host != "::1" or ma.port != 4401 or ma.peer_id != "lab-w":
        print(f"FAIL: parse_multiaddr ip6: {ma}")
        return 1
    if ma.to_string() != "/ip6/::1/tcp/4401/p2p/lab-w":
        print(f"FAIL: to_string ip6: {ma.to_string()}")
        return 1
    if Multiaddr(host="::1", port=9).to_string() != "/ip6/::1/tcp/9":
        print("FAIL: Multiaddr IPv6 formatting")
        return 1
    print("OK: multiaddr /ip6 parse + format")

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        try:
            hub_addrs = hub.listen("/ip6/::1/tcp/0")
        except Exception as exc:
            print(f"FAIL: IPv6 listen unsupported on this host: {exc}")
            return 1
        if not hub_addrs or "/ip6/" not in hub_addrs[0]:
            print(f"FAIL: expected /ip6 listen addr: {hub_addrs}")
            return 1
        hub_addr = hub_addrs[0]
        print(f"OK: hub listen {hub_addr}")

        # Dial-only client (Windows loopback listen+redial footgun).
        remote = client.dial(hub_addr)
        if remote != hub.peer_id:
            print(f"FAIL: dial remote {remote} != {hub.peer_id}")
            return 1
        if not _wait(lambda: hub.peer_id in client.connected_peers(), timeout=5.0):
            print(f"FAIL: not connected peers={client.connected_peers()}")
            return 1

        cm = client.metrics()
        hm = hub.metrics()
        if int(hm.get("libp2p_ipv6_listens", 0)) < 1:
            print(f"FAIL: hub ipv6_listens: {hm}")
            return 1
        if int(cm.get("libp2p_ipv6_dial_ok", 0)) < 1:
            print(f"FAIL: client ipv6_dial_ok: {cm}")
            return 1
        cap = client.capability_status()
        if not cap.get("ipv6"):
            print(f"FAIL: capability ipv6: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 22:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
        print(
            f"OK: ipv6 dial restored "
            f"listens={hm.get('libp2p_ipv6_listens')} "
            f"dial_ok={cm.get('libp2p_ipv6_dial_ok')}"
        )

        # Adapter builds /ip6 dial for IPv6 PeerEndpoint.
        from network.transport.libp2p_adapter import Libp2pTransportAdapter
        from network.transport.types import PeerEndpoint

        port = int(hub_addr.rsplit("/", 1)[-1])
        ad = Libp2pTransportAdapter(enabled=True, enable_mdns=False)
        # Fresh adapter node; dial hub via endpoint host ::1
        handle = ad.connect(PeerEndpoint(host="::1", port=port))
        if handle.get("backend") != "rust_libp2p":
            print(f"FAIL: adapter backend: {handle}")
            return 1
        if "/ip6/" not in str(handle.get("multiaddr") or ""):
            print(f"FAIL: adapter multiaddr not ip6: {handle}")
            return 1
        print("OK: adapter IPv6 dial path")
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_ipv6_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; IPv6 loopback; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
