#!/usr/bin/env python3
"""ADR 0019 Slice AK — connection attempt metrics lab.

Dialer sees ``libp2p_dialing``; allow-list deny bumps hub
``libp2p_incoming_connection_error`` (+ ``libp2p_allow_denied``).

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_connection_attempt_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 5.0, step: float = 0.05) -> bool:
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

    # --- Dialing path ---
    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        remote = client.dial(hub_addr)
        if remote != hub.peer_id:
            print(f"FAIL: dial remote {remote}")
            return 1
        if not _wait(
            lambda: int(client.metrics().get("libp2p_dialing", 0)) >= 1
            and int(client.metrics().get("libp2p_dial_ok", 0)) >= 1,
            timeout=4.0,
        ):
            print(f"FAIL: dialing metrics client={client.metrics()}")
            return 1
        print(
            f"OK: dialing={client.metrics().get('libp2p_dialing')} "
            f"dial_ok={client.metrics().get('libp2p_dial_ok')} "
            f"peer_external_addr={client.metrics().get('libp2p_peer_external_addr')}"
        )
        cap = client.capability_status()
        if not cap.get("connection_attempts"):
            print(f"FAIL: capability connection_attempts: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 36:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    # --- Incoming handshake error (allow-list deny) ---
    hub = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, enable_allow_list=True
    )
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        denied = False
        try:
            client.dial(hub_addr)
        except Exception:
            denied = True
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_incoming_connection_error", 0)) >= 1,
            timeout=4.0,
        ):
            if not denied:
                print(
                    f"FAIL: expected incoming_connection_error "
                    f"hub={hub.metrics()} client={client.metrics()}"
                )
                return 1
            print("WARN: dial denied but hub counter lag; checking allow_denied")
            if not _wait(
                lambda: int(hub.metrics().get("libp2p_allow_denied", 0)) >= 1,
                timeout=2.0,
            ):
                print(f"FAIL: no incoming error / allow_denied hub={hub.metrics()}")
                return 1
        hm = hub.metrics()
        print(
            f"OK: incoming_connection_error={hm.get('libp2p_incoming_connection_error')} "
            f"allow_denied={hm.get('libp2p_allow_denied')}"
        )
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_connection_attempt_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; connection attempts; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
