#!/usr/bin/env python3
"""ADR 0019 Slice AM — gossip subscription events + topic peers lab.

Remote ``Subscribed``/``Unsubscribed`` counters + ``gossip_topic_peers``.
(``gossip_mesh_peers`` may stay empty on tiny 2-node meshes.)

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_gossip_subscription_lab.py
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

    topic = str(getattr(abs_native, "ABS_GOSSIP_BLOCKS_TOPIC", "abs/blocks/1.0.0"))
    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        remote = client.dial(hub_addr)
        if remote != hub.peer_id:
            print(f"FAIL: dial remote {remote}")
            return 1

        hub.subscribe(topic)
        client.subscribe(topic)

        if not _wait(
            lambda: int(hub.metrics().get("libp2p_gossip_peer_subscribed", 0)) >= 1
            and int(client.metrics().get("libp2p_gossip_peer_subscribed", 0)) >= 1,
            timeout=6.0,
        ):
            print(
                f"FAIL: no peer_subscribed "
                f"hub={hub.metrics()} client={client.metrics()}"
            )
            return 1
        print(
            f"OK: peer_subscribed "
            f"hub={hub.metrics().get('libp2p_gossip_peer_subscribed')} "
            f"client={client.metrics().get('libp2p_gossip_peer_subscribed')}"
        )

        if not _wait(
            lambda: client.peer_id in hub.gossip_topic_peers(topic)
            and hub.peer_id in client.gossip_topic_peers(topic),
            timeout=6.0,
        ):
            print(
                f"FAIL: topic peers hub={hub.gossip_topic_peers(topic)} "
                f"client={client.gossip_topic_peers(topic)}"
            )
            return 1
        print(
            f"OK: topic_peers hub={hub.gossip_topic_peers(topic)} "
            f"client={client.gossip_topic_peers(topic)} "
            f"mesh_hub={hub.gossip_mesh_peers(topic)}"
        )

        unsub_before = int(hub.metrics().get("libp2p_gossip_peer_unsubscribed", 0))
        client.unsubscribe(topic)
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_gossip_peer_unsubscribed", 0))
            > unsub_before,
            timeout=6.0,
        ):
            print(f"FAIL: unsubscribe not observed hub={hub.metrics()}")
            return 1
        if not _wait(
            lambda: client.peer_id not in hub.gossip_topic_peers(topic),
            timeout=4.0,
        ):
            print(
                f"FAIL: topic peers still has client: {hub.gossip_topic_peers(topic)}"
            )
            return 1
        print(
            f"OK: peer_unsubscribed="
            f"{hub.metrics().get('libp2p_gossip_peer_unsubscribed')} "
            f"topic_peers={hub.gossip_topic_peers(topic)}"
        )

        cap = hub.capability_status()
        if not cap.get("gossip_subscription_events"):
            print(f"FAIL: capability gossip_subscription_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 38:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_gossip_subscription_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; gossip subscription events; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
