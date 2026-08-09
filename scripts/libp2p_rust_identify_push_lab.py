#!/usr/bin/env python3
"""ADR 0019 Slice BC — identify push + agent version lab.

With ``ABS_LIBP2P_IDENTIFY_PUSH=1`` and ``ABS_LIBP2P_AGENT_VERSION``,
``identify_push`` yields ``identify_pushed`` / remote ``identify_received``.
Capability ``identify_push`` / phase >= 54.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identify_push_lab.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AGENT = "absolute-slice-bc/0.1.0"


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

    prev_push = os.environ.get("ABS_LIBP2P_IDENTIFY_PUSH")
    prev_agent = os.environ.get("ABS_LIBP2P_AGENT_VERSION")
    os.environ["ABS_LIBP2P_IDENTIFY_PUSH"] = "1"
    os.environ["ABS_LIBP2P_AGENT_VERSION"] = AGENT

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        if not hub.metrics().get("libp2p_identify_push"):
            print(f"FAIL: identify push not enabled: {hub.metrics()}")
            return 1
        if hub.metrics().get("libp2p_agent_version") != AGENT:
            print(
                f"FAIL: agent_version "
                f"{hub.metrics().get('libp2p_agent_version')!r} want {AGENT!r}"
            )
            return 1
        proto = str(
            getattr(abs_native, "ABS_IDENTIFY_PROTOCOL_VERSION", "/absolute/1.0.0")
        )
        if hub.metrics().get("libp2p_protocol_version") != proto:
            print(
                f"FAIL: protocol_version "
                f"{hub.metrics().get('libp2p_protocol_version')!r} want {proto!r}"
            )
            return 1

        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        client.listen("/ip4/127.0.0.1/tcp/0")
        client.dial(hub_addr)
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_identify_received", 0)) >= 1
            and int(client.metrics().get("libp2p_identify_received", 0)) >= 1,
            timeout=6.0,
        ):
            print(
                f"FAIL: initial identify "
                f"hub={hub.metrics()} client={client.metrics()}"
            )
            return 1

        before_pushed = int(hub.metrics().get("libp2p_identify_pushed", 0))
        before_req = int(hub.metrics().get("libp2p_identify_push_requests", 0))
        before_recv = int(client.metrics().get("libp2p_identify_received", 0))
        n = hub.identify_push(client.peer_id)
        if n < 1:
            print(f"FAIL: identify_push targeted {n}")
            return 1
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_identify_pushed", 0)) > before_pushed
            and int(hub.metrics().get("libp2p_identify_push_requests", 0)) > before_req
            and int(client.metrics().get("libp2p_identify_received", 0)) > before_recv,
            timeout=5.0,
        ):
            print(
                f"FAIL: push events "
                f"hub={hub.metrics()} client={client.metrics()}"
            )
            return 1

        info = client.identify_info(hub.peer_id)
        if info.get("agent_version") != AGENT:
            print(f"FAIL: identify_info agent {info}")
            return 1

        # Listen-addr change should also trigger push when env enabled.
        before_listen_push = int(hub.metrics().get("libp2p_identify_pushed", 0))
        hub.listen("/ip4/127.0.0.1/tcp/0")
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_identify_pushed", 0))
            > before_listen_push,
            timeout=5.0,
        ):
            print(
                f"FAIL: listen-addr push "
                f"hub={hub.metrics()} before={before_listen_push}"
            )
            return 1

        hm = hub.metrics()
        cm = client.metrics()
        print(
            f"OK: push_requests={hm.get('libp2p_identify_push_requests')} "
            f"pushed={hm.get('libp2p_identify_pushed')} "
            f"client_recv={cm.get('libp2p_identify_received')} "
            f"agent={hm.get('libp2p_agent_version')}"
        )

        cap = hub.capability_status()
        if not cap.get("identify_push"):
            print(f"FAIL: capability identify_push: {cap}")
            return 1
        if not cap.get("identify_push_listen_addr"):
            print(f"FAIL: capability identify_push_listen_addr: {cap}")
            return 1
        if cap.get("agent_version") != AGENT:
            print(f"FAIL: capability agent_version: {cap.get('agent_version')!r}")
            return 1
        if int(cap.get("phase", 0)) < 54:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass
        if prev_push is None:
            os.environ.pop("ABS_LIBP2P_IDENTIFY_PUSH", None)
        else:
            os.environ["ABS_LIBP2P_IDENTIFY_PUSH"] = prev_push
        if prev_agent is None:
            os.environ.pop("ABS_LIBP2P_AGENT_VERSION", None)
        else:
            os.environ["ABS_LIBP2P_AGENT_VERSION"] = prev_agent

    print("OK: libp2p_rust_identify_push_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; identify push; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
