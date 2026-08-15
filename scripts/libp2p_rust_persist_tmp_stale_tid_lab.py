#!/usr/bin/env python3
"""ADR 0019 Slice CV — sweep stale other-tid persist tmp.

CU staging is ``dest.{pid}.{tid}.tmp``. Persist runs on a swarm worker.
A crash on worker A leaves that tid's tmp; a retry on worker B would miss
it. Slice CV unlinks stale ``dest.{pid}.*.tmp`` that are not in the
process in-flight set (concurrent writers). Capability
``persist_tmp_stale_tid_sweep`` / phase >= 99.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_persist_tmp_stale_tid_lab.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _staging_tmps(dest: Path) -> list[Path]:
    return sorted(dest.parent.glob(dest.name + ".*.tmp"))


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    want = "unlink_not_in_flight"
    mod_strategy = str(getattr(abs_native, "PERSIST_TMP_STALE_TID_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-tmp-stale-") as td:
        store = Path(td) / "external_addrs.json"
        stale = Path(str(store) + f".{os.getpid()}.StaleTid.tmp")
        foreign = Path(str(store) + ".999999999.OtherPid.tmp")
        stale.write_text("{stale-tid", encoding="utf-8")
        foreign.write_text("{other-pid", encoding="utf-8")
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            external_addrs_path=str(store),
        )
        try:
            cap = node.capability_status()
            if not cap.get("persist_tmp_stale_tid_sweep"):
                print(f"FAIL: capability persist_tmp_stale_tid_sweep: {cap}")
                return 1
            if cap.get("persist_tmp_stale_tid_strategy") != want:
                print(
                    "FAIL: capability strategy "
                    f"{cap.get('persist_tmp_stale_tid_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 99:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            if not node.add_external_address("/ip4/203.0.113.99/tcp/4099"):
                print("FAIL: add_external_address returned False")
                return 1
        finally:
            node.close()

        if not store.is_file():
            print("FAIL: dest missing after persist")
            return 1
        if stale.exists():
            print(f"FAIL: stale other-tid tmp not swept: {stale}")
            return 1
        if not foreign.exists():
            print("FAIL: unlinked another-pid staging tmp")
            return 1
        leftovers = [p for p in _staging_tmps(store) if p != foreign]
        if leftovers:
            print(f"FAIL: unexpected leftover tmp: {leftovers}")
            return 1
        print(f"OK: stale other-tid swept strategy={want} foreign_kept=True")

    print("OK: libp2p_rust_persist_tmp_stale_tid_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; stale other-tid tmp swept; "
        "in-flight writers skipped; not POSIX inode-atomic on NTFS; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
