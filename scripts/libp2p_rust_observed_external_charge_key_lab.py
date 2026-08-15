#!/usr/bin/env python3
"""ADR 0019 Slice CZ — Identify observed confirm charges the canonical key.

Identify ``observed_addr`` often appends ``/p2p/<peer>``. Crate ExternalAddresses
equality includes that suffix, so confirming the raw string after 20 charged
unique addrs silently evicts (or occupies a second unique slot). Slice CZ
admits and books ``advertised_charge_key`` (suffix stripped). Lab: fill 20
charged, identify, ``confirm_observed_addr``; unique used stays 20; crate still
has every charged addr; no extra ``/p2p/`` unique slot.

Capability ``observed_external_charge_key`` / phase >= 103.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_observed_external_charge_key_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BOOK = 20
WANT = "admit_canonical_charge_key"


def _wait(pred, timeout: float = 8.0, step: float = 0.1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return False


def _charge_key(addr: str) -> str:
    parts = addr.strip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "p2p" and parts[-1] != "p2p-circuit":
        return "/" + "/".join(parts[:-2])
    return addr


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    mod_strategy = str(
        getattr(abs_native, "OBSERVED_EXTERNAL_CHARGE_KEY_STRATEGY", "")
    )
    if mod_strategy != WANT:
        print(f"FAIL: module strategy {mod_strategy!r} != {WANT}")
        return 1

    book = int(getattr(abs_native, "LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX", 0) or 0)
    if book != BOOK:
        print(f"FAIL: libp2p ExternalAddresses book max {book}")
        return 1

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    listener = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        cap = listener.capability_status()
        if not cap.get("observed_external_charge_key"):
            print(f"FAIL: capability observed_external_charge_key: {cap}")
            return 1
        if cap.get("observed_external_charge_key_strategy") != WANT:
            print(
                "FAIL: capability strategy "
                f"{cap.get('observed_external_charge_key_strategy')!r} != {WANT}"
            )
            return 1
        if int(cap.get("phase", 0)) < 103:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1

        h_tcp = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        l_tcp = listener.listen("/ip4/127.0.0.1/tcp/0")[0]
        if not _wait(lambda: l_tcp in listener.external_addrs(), timeout=4.0):
            print(f"FAIL: listen not charged: {listener.external_addrs()}")
            return 1

        charged = [l_tcp]
        i = 0
        while int(listener.metrics().get("libp2p_advertised_externals_used", 0)) < book:
            if i >= 40:
                print(
                    "FAIL: could not fill advertised book: "
                    f"used={listener.metrics().get('libp2p_advertised_externals_used')}"
                )
                return 1
            addr = f"/ip4/203.0.113.{(i % 250) + 1}/tcp/{4400 + i}"
            if listener.add_external_address(addr):
                charged.append(addr)
            i += 1
        used0 = int(listener.metrics().get("libp2p_advertised_externals_used", 0))
        if used0 != book:
            print(f"FAIL: used {used0} after filling book {book}")
            return 1
        print(f"OK: filled {book} charged")

        crate0 = list(listener.swarm_external_addrs())
        missing0 = [a for a in charged if a not in crate0]
        if missing0:
            print(f"FAIL: charged missing from crate book before identify: {missing0}")
            return 1

        listener.dial(f"{h_tcp}/p2p/{hub.peer_id}")
        if not _wait(
            lambda: bool(
                str(listener.metrics().get("libp2p_last_observed_addr", "")).strip()
            ),
            timeout=6.0,
        ):
            print(f"FAIL: no observed addr: {listener.metrics()}")
            return 1
        obs = str(listener.metrics().get("libp2p_last_observed_addr", ""))
        key = _charge_key(obs)
        print(f"OK: observed {obs} charge_key {key}")

        try:
            confirmed = listener.confirm_observed_addr()
            print(f"OK: confirm returned {confirmed}")
        except Exception as exc:
            print(f"  confirm note (at cap expected refuse or already-charged): {exc}")

        used = int(listener.metrics().get("libp2p_advertised_externals_used", 0))
        if used > book:
            print(f"FAIL: unique used grew past book used={used} book={book}")
            return 1
        if used != book:
            print(f"FAIL: unique used changed used={used} want {book}")
            return 1
        crate = list(listener.swarm_external_addrs())
        missing = [a for a in charged if a not in crate]
        if missing:
            print(f"FAIL: charged evicted from crate book after confirm: {missing}")
            return 1
        suffix_slots = [
            a
            for a in list(listener.external_addrs())
            if a != key and _charge_key(a) == key and a != l_tcp
        ]
        if suffix_slots:
            print(f"FAIL: suffix occupied a second unique slot: {suffix_slots}")
            return 1
        print(
            f"OK: used still {used}; crate_len={len(crate)} "
            f"obs={obs} key={key}"
        )
    finally:
        for n in (listener, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_observed_external_charge_key_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; observed confirm charges canonical key; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
