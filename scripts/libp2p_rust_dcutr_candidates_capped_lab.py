#!/usr/bin/env python3
"""ADR 0019 Slice CB — DCUtR hole-punch candidates respect the advertised cap.

DCUtR 0.12 stores every ``NewExternalAddrCandidate`` (Identify observed /
translated listen) and sends them in hole-punch CONNECT. Uncharged addrs
(over-cap expansion sockets, ephemeral outbound when the cap is full) must
be omitted, not punched. Circuit ``/p2p-circuit`` stays outside the cap
(DCUtR already skips relayed). Capability ``dcutr_candidates_capped`` /
phase >= 79.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_dcutr_candidates_capped_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OP = "/ip4/203.0.113.80/tcp/4080"


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

    hub = abs_native.libp2p_node_new(
        enable_mdns=False,
        enable_reconnect=False,
        max_advertised_external=1,
    )
    client = abs_native.libp2p_node_new(
        enable_mdns=False,
        enable_reconnect=False,
        max_advertised_external=1,
    )
    try:
        cap = hub.capability_status()
        if not cap.get("dcutr_candidates_capped"):
            print(f"FAIL: capability dcutr_candidates_capped: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 79:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1

        if not client.add_external_address(OP):
            print("FAIL: client operator add False")
            return 1
        used_c = int(client.metrics().get("libp2p_advertised_externals_used", 0))
        if used_c != 1:
            print(f"FAIL: client used {used_c} after operator add")
            return 1

        hub_addrs = hub.listen("/ip4/127.0.0.1/tcp/0")
        if not hub_addrs:
            print("FAIL: hub listen empty")
            return 1
        client.dial(hub_addrs[0])
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_identify_received", 0)) >= 1
            and int(client.metrics().get("libp2p_identify_received", 0)) >= 1,
            timeout=6.0,
        ):
            print(
                f"FAIL: identify "
                f"hub={hub.metrics()} client={client.metrics()}"
            )
            return 1
        time.sleep(0.3)

        hub_adv = int(hub.metrics().get("libp2p_dcutr_advertised_candidates", -1))
        hub_omitted = int(hub.metrics().get("libp2p_dcutr_candidate_omitted", -1))
        hub_used = int(hub.metrics().get("libp2p_advertised_externals_used", 0))
        client_adv = int(client.metrics().get("libp2p_dcutr_advertised_candidates", -1))
        client_omitted = int(client.metrics().get("libp2p_dcutr_candidate_omitted", -1))
        print(
            f"OK: hub_adv={hub_adv} hub_omitted={hub_omitted} hub_used={hub_used} "
            f"client_adv={client_adv} client_omitted={client_omitted}"
        )
        if hub_adv < 0 or client_adv < 0 or hub_omitted < 0 or client_omitted < 0:
            print("FAIL: missing DCUtR candidate metrics")
            return 1
        if hub_adv > 1:
            print(f"FAIL: hub DCUtR candidates {hub_adv} exceed cap 1")
            return 1
        if client_adv > 1:
            print(f"FAIL: client DCUtR candidates {client_adv} exceed cap 1")
            return 1
        if hub_used >= 1 and hub_adv < 1:
            print(
                f"FAIL: hub charged used={hub_used} but DCUtR advertised {hub_adv}"
            )
            return 1
        id_omitted = int(client.metrics().get("libp2p_identify_candidate_omitted", 0))
        if client_adv != 0:
            print(
                f"FAIL: client punch set {client_adv} must be empty "
                "(cap full, no listen)"
            )
            return 1
        if client_omitted < 1 and id_omitted < 1:
            print(
                "FAIL: client cap full + no listen should omit Identify "
                f"ephemeral candidate dcutr_omitted={client_omitted} "
                f"identify_omitted={id_omitted}"
            )
            return 1
    finally:
        try:
            hub.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass

    print("OK: libp2p_rust_dcutr_candidates_capped_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; DCUtR candidates capped; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
