#!/usr/bin/env python3
"""ADR 0019 Slice BI — auto-confirm observed-addr lab.

With ``ABS_LIBP2P_CONFIRM_OBSERVED_ADDR=1``, identify Received promotes
``last_observed_addr`` into the external book without an explicit call.
Capability ``confirm_observed_addr_auto`` / phase >= 60.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_confirm_observed_addr_auto_lab.py
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

    prev = os.environ.get("ABS_LIBP2P_CONFIRM_OBSERVED_ADDR")
    os.environ["ABS_LIBP2P_CONFIRM_OBSERVED_ADDR"] = "1"

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        if not client.metrics().get("libp2p_confirm_observed_addr"):
            print(f"FAIL: auto-confirm not enabled: {client.metrics()}")
            return 1
        if not hub.metrics().get("libp2p_confirm_observed_addr"):
            print(f"FAIL: hub auto-confirm not enabled: {hub.metrics()}")
            return 1

        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        client.listen("/ip4/127.0.0.1/tcp/0")
        client.dial(hub_addr)

        def _booked(node) -> bool:
            obs = str(node.metrics().get("libp2p_last_observed_addr", ""))
            if not obs:
                return False
            parts = obs.strip("/").split("/")
            key = obs
            if len(parts) >= 2 and parts[-2] == "p2p" and parts[-1] != "p2p-circuit":
                key = "/" + "/".join(parts[:-2])
            book = list(node.external_addrs())
            return key in book or obs in book

        if not _wait(
            lambda: int(client.metrics().get("libp2p_observed_addr_confirmed", 0)) >= 1
            and int(client.metrics().get("libp2p_observed_addr_updates", 0)) >= 1
            and _booked(client),
            timeout=6.0,
        ):
            print(
                f"FAIL: auto-confirm "
                f"client={client.metrics()} ext={client.external_addrs()}"
            )
            return 1

        # Hub side should also auto-confirm when it receives client's identify.
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_observed_addr_confirmed", 0)) >= 1
            and _booked(hub),
            timeout=4.0,
        ):
            print(
                f"FAIL: hub auto-confirm "
                f"hub={hub.metrics()} ext={hub.external_addrs()}"
            )
            return 1

        cm = client.metrics()
        hm = hub.metrics()
        print(
            f"OK: client_obs={cm.get('libp2p_last_observed_addr')} "
            f"confirmed={cm.get('libp2p_observed_addr_confirmed')} "
            f"hub_confirmed={hm.get('libp2p_observed_addr_confirmed')}"
        )

        cap = client.capability_status()
        if not cap.get("confirm_observed_addr_auto"):
            print(f"FAIL: capability confirm_observed_addr_auto: {cap}")
            return 1
        if not cap.get("confirm_observed_addr"):
            print(f"FAIL: capability confirm_observed_addr: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 60:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass
        if prev is None:
            os.environ.pop("ABS_LIBP2P_CONFIRM_OBSERVED_ADDR", None)
        else:
            os.environ["ABS_LIBP2P_CONFIRM_OBSERVED_ADDR"] = prev

    print("OK: libp2p_rust_confirm_observed_addr_auto_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; auto-confirm observed-addr; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
