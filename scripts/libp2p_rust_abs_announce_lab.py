#!/usr/bin/env python3
"""Absolute ADR 0008 frame over gossipsub announce (ADR 0019 Slice G).

Publishes an Absolute wire ``new_block`` lab envelope on abs/blocks and admits
it on receivers via NativeTransportAdapter ingress.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_abs_announce_lab.py
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
    encode_abs_wire_frame,
)


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    topic = str(getattr(abs_native, "ABS_GOSSIP_BLOCKS_TOPIC", "abs/blocks/1.0.0"))
    a = abs_native.libp2p_node_new()
    b = abs_native.libp2p_node_new()
    try:
        listen_a = a.listen("/ip4/127.0.0.1/tcp/0")[0]
        b.dial(listen_a)
        for _ in range(40):
            if a.connected_peers() and b.connected_peers():
                break
            time.sleep(0.05)

        a.subscribe(topic)
        b.subscribe(topic)
        time.sleep(1.0)

        frame = encode_abs_wire_frame(
            "new_block",
            {"height": 42, "hash": "lab", "lab": "slice-g"},
            codec="v1",
        )
        mid = a.publish(topic, frame)
        if not mid:
            print("FAIL: empty publish id")
            return 1

        got = None
        deadline = time.time() + 5.0
        while time.time() < deadline:
            for _peer, t, data in b.poll_gossip():
                if topic in str(t) or str(t) == topic:
                    got = bytes(data)
                    break
            if got is not None:
                break
            time.sleep(0.1)
        if got is None:
            print("FAIL: no gossip payload received")
            return 1

        decision = admit_abs_wire_frame(got, peer_id=a.peer_id)
        if not decision.ok or decision.frame is None:
            print(f"FAIL: admit rejected {decision.reject}")
            return 1
        if decision.frame.msg_type.lower() not in {"new_block", "newblock"}:
            # wire may preserve exact type casing from encode
            if "new_block" not in decision.frame.msg_type.lower():
                print(f"FAIL: unexpected type {decision.frame.msg_type!r}")
                return 1

        print("OK: libp2p_rust_abs_announce_lab PASS")
        print(f"  topic: {topic}")
        print(f"  publish_id: {mid}")
        print(f"  admitted: {decision.frame.msg_type}")
        print("  honesty: announce lab; not tip proof / not prod gossip mesh")
        return 0
    finally:
        for n in (a, b):
            try:
                n.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
