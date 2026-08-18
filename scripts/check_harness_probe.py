#!/usr/bin/env python3
"""Live 3-node harness check for the state_root lag-reply slice.

Does not start soak. Does not rebuild Docker.
Exit 0 = all three nodes reachable and peer_probe_ok.
Exit 2 = mesh not listening.
Exit 1 = mesh up but probe/harness failed.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any

NODES = (
    ("miner", "http://127.0.0.1:18180"),
    ("full1", "http://127.0.0.1:18181"),
    ("full2", "http://127.0.0.1:18182"),
)


def _get(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    rows: list[dict[str, Any]] = []
    reachable = 0
    bad = 0
    print(f"{'role':<8} {'h':>5} {'peers':>5} {'healthy':<8} {'probe':<10} failed")
    for role, base in NODES:
        row: dict[str, Any] = {"role": role, "url": base}
        try:
            st = _get(f"{base}/status", timeout=4.0)
            row["height"] = int(st.get("height", 0) or 0)
            row["peers"] = int(st.get("peers", st.get("peer_count", 0)) or 0)
            reachable += 1
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            print(f"{role:<8} {'DOWN':>5}")
            rows.append(row)
            continue
        try:
            # Full (not quick) so waiter budget is 8s, matching the wire flight.
            h = _get(f"{base}/chain/consistency/harness?peer_timeout=8", timeout=20.0)
            failed = h.get("failed_checks") or []
            probe = h.get("peer_probe_error")
            healthy = bool(h.get("harness_healthy"))
            row["harness_healthy"] = healthy
            row["peer_probe_error"] = probe
            row["failed_checks"] = failed
            mark = "OK" if healthy and probe is None else "FAIL"
            if mark != "OK":
                bad += 1
            print(
                f"{role:<8} {row['height']:>5} {row['peers']:>5} "
                f"{str(healthy):<8} {str(probe):<10} {failed}"
            )
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            bad += 1
            print(f"{role:<8} {row.get('height', 0):>5} harness error: {exc}")
        rows.append(row)

    if reachable == 0:
        print("MESH_DOWN — start/rebuild: .\\scripts\\docker_prod_3node.ps1 -KeepVolumes")
        return 2
    if reachable < 3 or bad:
        print("RESULT: FAIL live harness")
        return 1
    print("RESULT: PASS live harness")
    return 0


if __name__ == "__main__":
    sys.exit(main())
