#!/usr/bin/env python3
"""Mixed dual-stack lab: 1 native TCP+TLS selector + 1 rust-libp2p (ADR 0019).

Shows coexistence without flipping prod compose. Native side stays selector
intent; libp2p side carries ADR 0008 frame over `/abs/wire/1.0.0` when rust
backend is available.

Usage:
  python scripts/libp2p_mixed_dual_stack_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.transport.dual_stack import DualStackDialer
from network.transport.libp2p_adapter.wire_bridge import (
    admit_abs_wire_frame,
    encode_abs_wire_frame,
)
from network.transport.types import PeerEndpoint


def main() -> int:
    native = DualStackDialer(feature_libp2p=False)
    lib = DualStackDialer(feature_libp2p=True)

    assert native.active_kind == "native_tcp_tls"
    assert lib.active_kind == "libp2p"

    n_handle = native.dial(PeerEndpoint(host="127.0.0.1", port=5002, peer_id="tls-peer"))
    assert n_handle["kind"] == "native_tcp_tls"

    if not lib.libp2p.rust_backend:
        # Stub path still proves selector coexistence
        d = lib.dial(PeerEndpoint(host="127.0.0.1", port=4002, peer_id="lab-lib"))
        assert d["kind"] == "libp2p"
        print("OK: libp2p_mixed_dual_stack_lab PASS (stub libp2p)")
        print("  native: tcp+tls selector")
        print("  libp2p: phase-1 stub (rebuild with --features libp2p for wire)")
        print("  honesty: not prod mesh; docker_prod_3node unchanged")
        return 0

    a = lib.libp2p
    # Second rust node for real dial+wire
    import abs_native

    listener = abs_native.libp2p_node_new()
    try:
        listen = listener.listen("/ip4/127.0.0.1/tcp/0")[0]
        # parse port from multiaddr /ip4/127.0.0.1/tcp/PORT
        port = int(listen.rsplit("/", 1)[-1])
        handle = lib.dial(PeerEndpoint(host="127.0.0.1", port=port, peer_id=listener.peer_id))
        assert handle["kind"] == "libp2p"
        assert handle["handle"].get("connected") is True

        frame = encode_abs_wire_frame("ping", {"lab": "mixed"}, codec="v1")
        remote_pid = str(handle["handle"]["peer_id"])
        ack = a.send_wire(remote_pid, frame)
        if not (isinstance(ack, (bytes, bytearray)) and ack.startswith(b"OK:")):
            print(f"FAIL: bad ack {ack!r}")
            return 1

        for _ in range(50):
            inbox = listener.poll_inbox()
            if inbox:
                break
            time.sleep(0.05)
        else:
            print("FAIL: listener inbox empty")
            return 1
        _peer, payload = inbox[0]
        decision = admit_abs_wire_frame(payload, peer_id=a.peer_id or "dialer")
        if not decision.ok:
            print(f"FAIL: ADR 0008 admit rejected: {decision.reject}")
            return 1
        if decision.frame is None or decision.frame.msg_type.lower() != "ping":
            print(f"FAIL: unexpected frame {decision.frame}")
            return 1

        caps = lib.capability_status()
        print("OK: libp2p_mixed_dual_stack_lab PASS")
        print(f"  native_kind: {native.active_kind}")
        print(f"  libp2p_kind: {lib.active_kind} rust={lib.libp2p.rust_backend}")
        print(f"  wire: ADR0008 ping admitted; dial_ok={caps['libp2p'].get('libp2p_dial_ok')}")
        print("  honesty: FEATURE_LIBP2P lab; not prod TCP+TLS mesh")
        return 0
    finally:
        try:
            a.close()
        except Exception:
            pass
        try:
            listener.close()
        except Exception:
            pass
        try:
            lib.libp2p.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
