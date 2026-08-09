#!/usr/bin/env python3
"""ADR 0019 Slice Y — DNS multiaddr dial lab (/dns4/localhost).

Hub listens on loopback IPv4; client dials via ``/dns4/localhost/tcp/<port>``
using rust-libp2p DNS transport resolution.

Requires abs_native built with Cargo feature ``libp2p`` (+ ``dns``).

Usage:
  python scripts/libp2p_rust_dns_lab.py
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

    ma = parse_multiaddr("/dns4/localhost/tcp/4402/p2p/lab-y")
    if ma.host != "localhost" or ma.port != 4402 or ma.peer_id != "lab-y":
        print(f"FAIL: parse_multiaddr dns4: {ma}")
        return 1
    if ma.dns != "dns4":
        print(f"FAIL: dns field: {ma.dns}")
        return 1
    if ma.to_string() != "/dns4/localhost/tcp/4402/p2p/lab-y":
        print(f"FAIL: to_string dns4: {ma.to_string()}")
        return 1
    ma6 = parse_multiaddr("/dns6/localhost/tcp/9")
    if ma6.dns != "dns6" or ma6.to_string() != "/dns6/localhost/tcp/9":
        print(f"FAIL: dns6 roundtrip: {ma6}")
        return 1
    if Multiaddr(host="example.com", port=9).to_string() != "/dns4/example.com/tcp/9":
        print("FAIL: hostname defaults to dns4")
        return 1
    print("OK: multiaddr /dns4|/dns6 parse + format")

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addrs = hub.listen("/ip4/127.0.0.1/tcp/0")
        if not hub_addrs:
            print("FAIL: hub listen empty")
            return 1
        hub_addr = hub_addrs[0]
        port = int(hub_addr.rsplit("/", 1)[-1])
        print(f"OK: hub listen {hub_addr}")

        dns_addr = f"/dns4/localhost/tcp/{port}"
        # Dial-only client (Windows loopback listen+redial footgun).
        remote = client.dial(dns_addr)
        if remote != hub.peer_id:
            print(f"FAIL: dial remote {remote} != {hub.peer_id}")
            return 1
        if not _wait(lambda: hub.peer_id in client.connected_peers(), timeout=5.0):
            print(f"FAIL: not connected peers={client.connected_peers()}")
            return 1

        cm = client.metrics()
        if int(cm.get("libp2p_dns_dial_ok", 0)) < 1:
            print(f"FAIL: client dns_dial_ok: {cm}")
            return 1
        cap = client.capability_status()
        if not cap.get("dns"):
            print(f"FAIL: capability dns: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 24:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
        print(f"OK: dns4 dial restored dial_ok={cm.get('libp2p_dns_dial_ok')}")

        from network.transport.libp2p_adapter import Libp2pTransportAdapter
        from network.transport.types import PeerEndpoint

        ad = Libp2pTransportAdapter(enabled=True, enable_mdns=False)
        handle = ad.connect(PeerEndpoint(host="localhost", port=port))
        if handle.get("backend") != "rust_libp2p":
            print(f"FAIL: adapter backend: {handle}")
            return 1
        if "/dns4/" not in str(handle.get("multiaddr") or ""):
            print(f"FAIL: adapter multiaddr not dns4: {handle}")
            return 1
        print("OK: adapter DNS dial path")
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_dns_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; DNS multiaddr; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
