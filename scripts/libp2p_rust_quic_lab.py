#!/usr/bin/env python3
"""ADR 0019 Slice AB — QUIC listen/dial lab (/udp/.../quic-v1).

Hub listens on QUIC loopback; dial-only client connects via quic-v1 multiaddr.

Requires abs_native built with Cargo features ``libp2p`` + ``quic``.

Usage:
  python scripts/libp2p_rust_quic_lab.py
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

    ma = parse_multiaddr("/ip4/127.0.0.1/udp/4403/quic-v1/p2p/lab-ab")
    if ma.host != "127.0.0.1" or ma.port != 4403 or ma.peer_id != "lab-ab":
        print(f"FAIL: parse quic: {ma}")
        return 1
    if ma.transport != "quic-v1":
        print(f"FAIL: transport: {ma.transport}")
        return 1
    if ma.to_string() != "/ip4/127.0.0.1/udp/4403/quic-v1/p2p/lab-ab":
        print(f"FAIL: to_string quic: {ma.to_string()}")
        return 1
    if (
        Multiaddr(host="127.0.0.1", port=9, transport="quic-v1").to_string()
        != "/ip4/127.0.0.1/udp/9/quic-v1"
    ):
        print("FAIL: Multiaddr quic format")
        return 1
    print("OK: multiaddr /quic-v1 parse + format")

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        try:
            hub_addrs = hub.listen("/ip4/127.0.0.1/udp/0/quic-v1")
        except Exception as exc:
            print(f"FAIL: QUIC listen unsupported on this host: {exc}")
            return 1
        if not hub_addrs or "quic-v1" not in hub_addrs[0]:
            print(f"FAIL: expected quic listen addr: {hub_addrs}")
            return 1
        hub_addr = hub_addrs[0]
        print(f"OK: hub listen {hub_addr}")

        # Dial-only client.
        remote = client.dial(hub_addr)
        if remote != hub.peer_id:
            print(f"FAIL: dial remote {remote} != {hub.peer_id}")
            return 1
        if not _wait(lambda: hub.peer_id in client.connected_peers(), timeout=5.0):
            print(f"FAIL: not connected peers={client.connected_peers()}")
            return 1

        cm = client.metrics()
        hm = hub.metrics()
        if int(hm.get("libp2p_quic_listens", 0)) < 1:
            print(f"FAIL: hub quic_listens: {hm}")
            return 1
        if int(cm.get("libp2p_quic_dial_ok", 0)) < 1:
            print(f"FAIL: client quic_dial_ok: {cm}")
            return 1
        cap = client.capability_status()
        if not cap.get("quic"):
            print(f"FAIL: capability quic: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 27:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
        print(
            f"OK: quic dial restored "
            f"listens={hm.get('libp2p_quic_listens')} "
            f"dial_ok={cm.get('libp2p_quic_dial_ok')}"
        )

        # Wire over QUIC still works.
        payload = abs_native.libp2p_pack_wire("ping", b"quic-ab")
        ack = client.send_wire(hub.peer_id, payload)
        if not (isinstance(ack, (bytes, bytearray)) and bytes(ack).startswith(b"OK:")):
            print(f"FAIL: wire over quic: {ack!r}")
            return 1
        print("OK: /abs/wire over QUIC")
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_quic_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; QUIC opt-in; TCP+TLS remains default mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
