#!/usr/bin/env python3
"""ADR 0019 Slice AC — WebSocket listen/dial lab (/tcp/.../ws).

Hub listens on WebSocket loopback; dial-only client connects via /ws multiaddr.

Requires abs_native built with Cargo features ``libp2p`` + ``websocket``.

Usage:
  python scripts/libp2p_rust_websocket_lab.py
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

    ma = parse_multiaddr("/ip4/127.0.0.1/tcp/4404/ws/p2p/lab-ac")
    if ma.host != "127.0.0.1" or ma.port != 4404 or ma.peer_id != "lab-ac":
        print(f"FAIL: parse ws: {ma}")
        return 1
    if ma.transport != "ws":
        print(f"FAIL: transport: {ma.transport}")
        return 1
    if ma.to_string() != "/ip4/127.0.0.1/tcp/4404/ws/p2p/lab-ac":
        print(f"FAIL: to_string ws: {ma.to_string()}")
        return 1
    if Multiaddr(host="127.0.0.1", port=9, transport="ws").to_string() != (
        "/ip4/127.0.0.1/tcp/9/ws"
    ):
        print("FAIL: Multiaddr ws format")
        return 1
    print("OK: multiaddr /ws parse + format")

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        try:
            hub_addrs = hub.listen("/ip4/127.0.0.1/tcp/0/ws")
        except Exception as exc:
            print(f"FAIL: WebSocket listen unsupported on this host: {exc}")
            return 1
        if not hub_addrs or "/ws" not in hub_addrs[0]:
            print(f"FAIL: expected ws listen addr: {hub_addrs}")
            return 1
        hub_addr = hub_addrs[0]
        print(f"OK: hub listen {hub_addr}")

        # Dial-only client (avoid listen+redial WSAEADDRINUSE on Windows).
        remote = client.dial(hub_addr)
        if remote != hub.peer_id:
            print(f"FAIL: dial remote {remote} != {hub.peer_id}")
            return 1
        if not _wait(lambda: hub.peer_id in client.connected_peers(), timeout=5.0):
            print(f"FAIL: not connected peers={client.connected_peers()}")
            return 1

        cm = client.metrics()
        hm = hub.metrics()
        if int(hm.get("libp2p_ws_listens", 0)) < 1:
            print(f"FAIL: hub ws_listens: {hm}")
            return 1
        if int(cm.get("libp2p_ws_dial_ok", 0)) < 1:
            print(f"FAIL: client ws_dial_ok: {cm}")
            return 1
        cap = client.capability_status()
        if not cap.get("websocket"):
            print(f"FAIL: capability websocket: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 28:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
        print(
            f"OK: ws dial restored "
            f"listens={hm.get('libp2p_ws_listens')} "
            f"dial_ok={cm.get('libp2p_ws_dial_ok')}"
        )

        payload = abs_native.libp2p_pack_wire("ping", b"ws-ac")
        ack = client.send_wire(hub.peer_id, payload)
        if not (isinstance(ack, (bytes, bytearray)) and bytes(ack).startswith(b"OK:")):
            print(f"FAIL: wire over ws: {ack!r}")
            return 1
        print("OK: /abs/wire over WebSocket")
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_websocket_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; WebSocket opt-in; TCP+TLS remains default mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
