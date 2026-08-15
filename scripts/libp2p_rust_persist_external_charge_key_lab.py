#!/usr/bin/env python3
"""ADR 0019 Slice DB — persist JSON load collapses `/p2p/<peer>` charge key.

Operator JSON may still list ``listen/p2p/<peer>`` next to the transport
prefix. Exact-string dedupe treated those as two unique advertised addrs, so
restore occupied a second crate ExternalAddresses slot (silent eviction past
20). Slice DB canonicalizes on load. Lab: persist key+suffix; spawn restores
one unique; crate has the key, not the suffix.

Capability ``persist_external_charge_key`` / phase >= 105.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_persist_external_charge_key_lab.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WANT = "load_canonical_charge_key"
ADVERTISED = "/ip4/203.0.113.77/tcp/4077"


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

    mod_strategy = str(getattr(abs_native, "PERSIST_EXTERNAL_CHARGE_KEY_STRATEGY", ""))
    if mod_strategy != WANT:
        print(f"FAIL: module strategy {mod_strategy!r} != {WANT}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-persist-ck-") as td:
        store = Path(td) / "external_addrs.json"
        probe = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        try:
            peer = str(probe.peer_id)
        finally:
            try:
                probe.close()
            except Exception:
                pass

        suffix = f"{ADVERTISED}/p2p/{peer}"
        store.write_text(
            json.dumps({"version": 1, "addrs": [ADVERTISED, suffix]}, indent=2),
            encoding="utf-8",
        )

        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            external_addrs_path=str(store),
        )
        try:
            cap = node.capability_status()
            if not cap.get("persist_external_charge_key"):
                print(f"FAIL: capability persist_external_charge_key: {cap}")
                return 1
            if cap.get("persist_external_charge_key_strategy") != WANT:
                print(
                    "FAIL: capability strategy "
                    f"{cap.get('persist_external_charge_key_strategy')!r} != {WANT}"
                )
                return 1
            if int(cap.get("phase", 0)) < 105:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1

            if not _wait(lambda: ADVERTISED in node.external_addrs(), timeout=4.0):
                print(f"FAIL: advertised not restored: {node.external_addrs()}")
                return 1
            book = list(node.external_addrs())
            if suffix in book:
                print(f"FAIL: suffix occupied python book: {book}")
                return 1
            crate = list(node.swarm_external_addrs())
            if ADVERTISED not in crate:
                print(f"FAIL: advertised missing from crate: {crate}")
                return 1
            if suffix in crate:
                print(f"FAIL: suffix occupied crate book: {crate}")
                return 1
            print(
                f"OK: restored unique advertised crate_len={len(crate)} "
                f"suffix_collapsed peer={peer}"
            )
        finally:
            try:
                node.close()
            except Exception:
                pass

    print("OK: libp2p_rust_persist_external_charge_key_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; persist load collapses charge key; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
