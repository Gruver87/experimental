#!/usr/bin/env python3
"""Live 3-node check after catch-up + wire-probe honesty.

Does not start soak. Does not rebuild Docker.

Pass (exit 0):
  all three /health/ready == 200
  height gap <= 1
  each node peers >= 2
  topology_healthy, state_consistent, wire_probe_ok all true

Fail (exit 1) if any of those break. Mesh down = exit 2.
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


def _get(url: str, timeout: float) -> tuple[int, dict[str, Any]]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return int(resp.status), json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body: dict[str, Any] = {}
        try:
            body = json.loads(exc.read().decode())
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            body = {"status": str(exc.reason)}
        return int(exc.code), body


def main() -> int:
    print(
        f"{'role':<8} {'ready':>5} {'h':>5} {'peers':>5} "
        f"{'topo':<6} {'consist':<8} {'wire':<6} rate_drops"
    )
    rows: list[dict[str, Any]] = []
    reachable = 0
    for role, base in NODES:
        row: dict[str, Any] = {"role": role}
        try:
            code, ready = _get(f"{base}/health/ready", timeout=5.0)
            code_s, st = _get(f"{base}/status", timeout=5.0)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"{role:<8} DOWN {exc}")
            rows.append(row)
            continue
        reachable += 1
        checks = ready.get("checks") if isinstance(ready, dict) else {}
        if not isinstance(checks, dict):
            checks = {}
        p2p = st.get("p2p_summary") if isinstance(st, dict) else {}
        if not isinstance(p2p, dict):
            p2p = {}
        sec = p2p.get("security") if isinstance(p2p.get("security"), dict) else {}
        row["ready_code"] = int(code)
        row["ready_status"] = str(ready.get("status") or "")
        row["height"] = int(st.get("height") or 0) if code_s == 200 else -1
        row["peers"] = int(st.get("peers") or st.get("peer_count") or 0)
        row["topo"] = bool(p2p.get("topology_healthy"))
        row["consist"] = bool(checks.get("state_consistent"))
        row["wire"] = bool(checks.get("wire_probe_ok"))
        row["rate_drops"] = int(sec.get("rate_limit_drops") or 0)
        print(
            f"{role:<8} {row['ready_code']:>5} {row['height']:>5} {row['peers']:>5} "
            f"{str(row['topo']):<6} {str(row['consist']):<8} {str(row['wire']):<6} "
            f"{row['rate_drops']}"
        )
        rows.append(row)

    if reachable == 0:
        print("MESH_DOWN — rebuild: .\\scripts\\docker_prod_3node.ps1 -KeepVolumes")
        return 2

    heights = [int(r["height"]) for r in rows if "height" in r and int(r["height"]) >= 0]
    gap = (max(heights) - min(heights)) if heights else 99
    ready_ok = all(int(r.get("ready_code") or 0) == 200 for r in rows if r.get("role"))
    peers_ok = all(int(r.get("peers") or 0) >= 2 for r in rows if "peers" in r)
    n = len([r for r in rows if "height" in r])

    consist_ok = all(bool(r.get("consist")) for r in rows if "consist" in r)
    topo_ok = all(bool(r.get("topo")) for r in rows if "topo" in r)
    wire_ok = all(bool(r.get("wire")) for r in rows if "wire" in r)

    print(
        f"height_gap={gap} ready_200={ready_ok} peers_ge2={peers_ok} "
        f"consist={consist_ok} topo={topo_ok} wire={wire_ok} nodes={n}/3"
    )
    if (
        n < 3
        or (not ready_ok)
        or gap > 1
        or (not peers_ok)
        or (not consist_ok)
        or (not topo_ok)
        or (not wire_ok)
    ):
        print("RESULT: FAIL live mesh (catch-up/topology/wire)")
        print(
            "  ready 200 + gap<=1 + peers>=2 + consist + topo + wire required. "
            "Soak not claimed."
        )
        return 1
    print("RESULT: PASS live mesh (ready + heights + peers + consist + topo + wire)")
    print("  Soak not run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
