#!/usr/bin/env python3
"""ADR 0019 Slice BA — deferred gossip validation lab.

With ``ABS_LIBP2P_GOSSIP_DEFER_VALIDATION=1``, receiver must
``report_gossip_validation`` (reject then ignore). Capability
``gossip_validation_events`` / phase >= 52.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_gossip_validation_lab.py
"""

from __future__ import annotations

import os
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

    prev = os.environ.get("ABS_LIBP2P_GOSSIP_DEFER_VALIDATION")
    os.environ["ABS_LIBP2P_GOSSIP_DEFER_VALIDATION"] = "1"

    topic = str(getattr(abs_native, "ABS_GOSSIP_BLOCKS_TOPIC", "abs/blocks/1.0.0"))
    a = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    b = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        if not b.metrics().get("libp2p_gossip_defer_validation"):
            print(f"FAIL: defer not enabled: {b.metrics()}")
            return 1

        a_addr = a.listen("/ip4/127.0.0.1/tcp/0")[0]
        b.listen("/ip4/127.0.0.1/tcp/0")
        b.dial(a_addr)
        if not _wait(
            lambda: a.peer_id in b.connected_peers()
            and b.peer_id in a.connected_peers(),
            timeout=5.0,
        ):
            print("FAIL: peers not connected")
            return 1

        a.subscribe(topic)
        b.subscribe(topic)
        time.sleep(0.8)

        # Reject path.
        mid = a.publish(topic, b"slice-ba-reject")
        if not mid:
            print("FAIL: empty publish id")
            return 1
        if not _wait(
            lambda: int(b.metrics().get("libp2p_gossip_validation_pending", 0)) >= 1
            and str(b.metrics().get("libp2p_last_gossip_message_id", "")),
            timeout=5.0,
        ):
            print(f"FAIL: pending message missing b={b.metrics()}")
            return 1

        last_id = str(b.metrics().get("libp2p_last_gossip_message_id", ""))
        last_peer = str(b.metrics().get("libp2p_last_gossip_propagation_peer", ""))
        if last_peer != a.peer_id:
            print(f"FAIL: propagation peer {last_peer} != {a.peer_id}")
            return 1
        before_rej = int(b.metrics().get("libp2p_gossip_validation_reject", 0))
        if not b.report_gossip_validation(last_id, last_peer, "reject"):
            # forwarded=false is OK; just need counter bump / no exception
            pass
        if not _wait(
            lambda: int(b.metrics().get("libp2p_gossip_validation_reject", 0))
            > before_rej,
            timeout=3.0,
        ):
            print(f"FAIL: reject counter b={b.metrics()}")
            return 1
        print(
            f"OK: reject mid={last_id} "
            f"reject={b.metrics().get('libp2p_gossip_validation_reject')}"
        )

        # Ignore path.
        mid2 = a.publish(topic, b"slice-ba-ignore")
        if not mid2:
            print("FAIL: empty publish id (ignore)")
            return 1
        if not _wait(
            lambda: str(b.metrics().get("libp2p_last_gossip_message_id", ""))
            not in ("", last_id)
            or int(b.metrics().get("libp2p_gossip_validation_pending", 0)) >= 1,
            timeout=5.0,
        ):
            print(f"FAIL: second pending missing b={b.metrics()}")
            return 1
        last_id2 = str(b.metrics().get("libp2p_last_gossip_message_id", ""))
        last_peer2 = str(b.metrics().get("libp2p_last_gossip_propagation_peer", ""))
        before_ign = int(b.metrics().get("libp2p_gossip_validation_ignore", 0))
        b.report_gossip_validation(last_id2, last_peer2, "ignore")
        if not _wait(
            lambda: int(b.metrics().get("libp2p_gossip_validation_ignore", 0))
            > before_ign,
            timeout=3.0,
        ):
            print(f"FAIL: ignore counter b={b.metrics()}")
            return 1
        print(
            f"OK: ignore mid={last_id2} "
            f"ignore={b.metrics().get('libp2p_gossip_validation_ignore')}"
        )

        cap = b.capability_status()
        if not cap.get("gossip_validation_events"):
            print(f"FAIL: capability gossip_validation_events: {cap}")
            return 1
        if not cap.get("gossip_defer_validation"):
            print(f"FAIL: capability gossip_defer_validation: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 52:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (a, b):
            try:
                n.close()
            except Exception:
                pass
        if prev is None:
            os.environ.pop("ABS_LIBP2P_GOSSIP_DEFER_VALIDATION", None)
        else:
            os.environ["ABS_LIBP2P_GOSSIP_DEFER_VALIDATION"] = prev

    print("OK: libp2p_rust_gossip_validation_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; gossip validation defer; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
