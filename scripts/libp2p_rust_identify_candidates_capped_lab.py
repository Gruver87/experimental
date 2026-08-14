#!/usr/bin/env python3
"""ADR 0019 Slice CC — Identify omits uncharged NewExternalAddrCandidate.

Identify 0.45 broadcasts observed / translated listen addrs as
``ToSwarm::NewExternalAddrCandidate`` (swarm-wide, not only DCUtR).
Uncharged addrs must be omitted at the source. Circuit stays outside the
cap. Capability ``identify_candidates_capped`` / phase >= 80.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identify_candidates_capped_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OP = "/ip4/203.0.113.81/tcp/4081"


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
        if not cap.get("identify_candidates_capped"):
            print(f"FAIL: capability identify_candidates_capped: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 80:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1

        if not client.add_external_address(OP):
            print("FAIL: client operator add False")
            return 1

        hub_addrs = hub.listen("/ip4/127.0.0.1/tcp/0")
        if not hub_addrs:
            print("FAIL: hub listen empty")
            return 1
        before = int(client.metrics().get("libp2p_external_addr_candidates", 0))
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

        omitted = int(client.metrics().get("libp2p_identify_candidate_omitted", -1))
        candidates = int(client.metrics().get("libp2p_external_addr_candidates", 0))
        dcutr_adv = int(client.metrics().get("libp2p_dcutr_advertised_candidates", -1))
        print(
            f"OK: client identify_omitted={omitted} swarm_candidates={candidates} "
            f"(before={before}) dcutr_adv={dcutr_adv}"
        )
        if omitted < 0 or dcutr_adv < 0:
            print("FAIL: missing Identify/DCUtR candidate metrics")
            return 1
        if omitted < 1:
            print(f"FAIL: Identify should omit uncharged candidate omitted={omitted}")
            return 1
        if candidates > before:
            print(
                f"FAIL: uncharged candidate leaked to swarm "
                f"before={before} after={candidates}"
            )
            return 1
        if dcutr_adv != 0:
            print(f"FAIL: DCUtR punch set {dcutr_adv} after Identify omit")
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

    print("OK: libp2p_rust_identify_candidates_capped_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; Identify candidates capped; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
