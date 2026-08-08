#!/usr/bin/env python3
"""ADR 0019 Slice M — Absolute ADR 0008 v1/v2 over `/abs/wire/1.0.0`.

Proves NDJSON (v1) and Borsh AB2 (v2) frames round-trip on rust-libp2p
request-response, with native codec counters + Python admit.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_abs_wire_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.transport.libp2p_adapter.wire_bridge import (
    admit_abs_wire_frame,
    detect_abs_wire_codec,
    encode_abs_wire_frame,
)


def _wait_connected(a, b, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if a.connected_peers() and b.connected_peers():
            return True
        time.sleep(0.05)
    return False


def _poll_one(node, timeout: float = 3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        inbox = node.poll_inbox()
        if inbox:
            return inbox[0]
        time.sleep(0.05)
    return None


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    if abs_native.libp2p_classify_abs_wire(b'{"type":"ping"}\n') != "v1":
        print("FAIL: classify v1")
        return 1
    if abs_native.libp2p_classify_abs_wire(b"AB2:aa\n") != "v2":
        print("FAIL: classify v2")
        return 1

    a = abs_native.libp2p_node_new(enable_mdns=False)
    b = abs_native.libp2p_node_new(enable_mdns=False)
    try:
        listen_a = a.listen("/ip4/127.0.0.1/tcp/0")[0]
        b.dial(listen_a)
        if not _wait_connected(a, b):
            print("FAIL: peers not connected")
            return 1

        for codec in ("v1", "v2"):
            frame = encode_abs_wire_frame(
                "ping",
                {"lab": "slice-m", "codec": codec},
                codec=codec,
            )
            detected = detect_abs_wire_codec(frame)
            if detected != codec:
                print(f"FAIL: detect {codec} got {detected}")
                return 1
            ack = b.send_wire(a.peer_id, frame)
            if not (isinstance(ack, (bytes, bytearray)) and ack.startswith(b"OK:")):
                print(f"FAIL: bad ack codec={codec}: {ack!r}")
                return 1
            got = _poll_one(a)
            if got is None:
                print(f"FAIL: inbox empty codec={codec}")
                return 1
            peer_from, payload = got
            if peer_from != b.peer_id:
                print(f"FAIL: inbox peer {peer_from}")
                return 1
            if detect_abs_wire_codec(payload) != codec:
                print(f"FAIL: recv codec mismatch for {codec}")
                return 1
            decision = admit_abs_wire_frame(bytes(payload), peer_id=b.peer_id)
            if not decision.ok or decision.frame is None:
                print(f"FAIL: admit {codec}: ok={decision.ok} reject={decision.reject}")
                return 1
            if str(decision.frame.msg_type).lower() != "ping":
                print(f"FAIL: admit msg_type={decision.frame.msg_type!r}")
                return 1
            print(f"OK: abs_wire codec={codec} admit=ping")

        ma = a.metrics()
        mb = b.metrics()
        if int(mb.get("libp2p_abs_wire_v1_sent", 0)) < 1:
            print(f"FAIL: v1_sent metrics {mb}")
            return 1
        if int(mb.get("libp2p_abs_wire_v2_sent", 0)) < 1:
            print(f"FAIL: v2_sent metrics {mb}")
            return 1
        if int(ma.get("libp2p_abs_wire_v1_recv", 0)) < 1:
            print(f"FAIL: v1_recv metrics {ma}")
            return 1
        if int(ma.get("libp2p_abs_wire_v2_recv", 0)) < 1:
            print(f"FAIL: v2_recv metrics {ma}")
            return 1
        cap = a.capability_status()
        if int(cap.get("phase", 0)) < 12:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
        if not cap.get("abs_wire_codecs"):
            print(f"FAIL: abs_wire_codecs capability: {cap}")
            return 1

        # Adapter path: send_abs_wire + poll_admit_inbox
        from network.transport.libp2p_adapter import Libp2pTransportAdapter

        hub = abs_native.libp2p_node_new(enable_mdns=False)
        ad = Libp2pTransportAdapter(enabled=True, enable_mdns=False)
        try:
            hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
            ad.listen("/ip4/127.0.0.1/tcp/0")
            ad_node = ad._ensure_node()
            ad_node.dial(hub_addr)
            for _ in range(40):
                if hub.connected_peers() and ad_node.connected_peers():
                    break
                time.sleep(0.05)
            ack = ad.send_abs_wire(
                hub.peer_id,
                "ping",
                {"lab": "adapter-m"},
                codec="v2",
            )
            if not ack.startswith(b"OK:"):
                print(f"FAIL: adapter send_abs_wire ack {ack!r}")
                return 1
            got = _poll_one(hub)
            if got is None:
                print("FAIL: hub inbox empty after adapter send")
                return 1
            decision = admit_abs_wire_frame(bytes(got[1]), peer_id=ad.peer_id)
            if not decision.ok:
                print(f"FAIL: adapter frame admit: {decision.reject}")
                return 1
            print("OK: adapter send_abs_wire v2")
        finally:
            try:
                ad.close()
            except Exception:
                pass
            try:
                hub.close()
            except Exception:
                pass

        print("OK: libp2p_rust_abs_wire_lab PASS")
        print(
            f"  metrics: sent_v1={mb.get('libp2p_abs_wire_v1_sent')} "
            f"sent_v2={mb.get('libp2p_abs_wire_v2_sent')} "
            f"recv_v1={ma.get('libp2p_abs_wire_v1_recv')} "
            f"recv_v2={ma.get('libp2p_abs_wire_v2_recv')}"
        )
        print("  honesty: FEATURE_LIBP2P lab; ADR 0008 over libp2p; not prod mesh")
        return 0
    finally:
        for n in (a, b):
            try:
                n.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
