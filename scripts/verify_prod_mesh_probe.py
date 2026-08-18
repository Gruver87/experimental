#!/usr/bin/env python3
"""Verify production 3-node mesh HTTP health (:18180-:18182, chain 778888)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.mainnet_constants import MAINNET_V1_CHAIN_ID

DEFAULT_NODES = (
    "http://127.0.0.1:18180",
    "http://127.0.0.1:18181",
    "http://127.0.0.1:18182",
)


ALIGN_STATUS_RETRIES = 4
ALIGN_STATUS_SLEEP_SEC = 3.0


def _api(url: str, timeout: float = 10.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _probe_ready(base_url: str, timeout: float = 5.0) -> bool:
    try:
        row = _api(f"{base_url.rstrip('/')}/health/ready", timeout=timeout)
        return str(row.get("status", "")).lower() == "ready"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return False


def _mesh_alignment_errors(nodes: list[dict[str, Any]]) -> list[str]:
    """Hard-fail fork/skew. Callers retry around mining-window 1-height races."""
    errors: list[str] = []
    heights = [n.get("height", 0) for n in nodes if n.get("reachable")]
    if heights and max(heights) - min(heights) > 1:
        errors.append(f"height spread across mesh: {heights}")
    heads = [n.get("head_hash") for n in nodes if n.get("reachable") and n.get("head_hash")]
    if len(heads) >= 2 and len(set(heads)) > 1:
        errors.append("head hash mismatch across reachable nodes")
    roots = [n.get("state_root") for n in nodes if n.get("reachable") and n.get("state_root")]
    if len(roots) >= 2 and len(set(roots)) > 1:
        errors.append("state root mismatch across reachable nodes")
    return errors


def _refresh_status_fields(url: str, row: dict[str, Any]) -> None:
    st = _api(f"{url}/status", timeout=10)
    row["height"] = int(st.get("height", 0) or 0)
    row["peers"] = int(st.get("peers", st.get("peer_count", 0)) or 0)
    row["chain_id"] = int(st.get("chain_id", 0) or 0)
    row["deployment_mode"] = st.get("deployment_mode")
    row["head_hash"] = st.get("head_hash")


def verify_prod_mesh_probe(
    *,
    node_urls: list[str] | None = None,
    wait_sec: int = 0,
    deep: bool = True,
) -> tuple[list[str], list[str], dict[str, Any]]:
    import time

    errors: list[str] = []
    warnings: list[str] = []
    urls = [u.rstrip("/") for u in (node_urls or list(DEFAULT_NODES)) if u]

    deadline = time.time() + max(0, wait_sec)
    reachable: list[str] = []
    while True:
        reachable = [u for u in urls if _probe_ready(u)]
        if len(reachable) == len(urls) or time.time() >= deadline:
            break
        time.sleep(3)

    nodes: list[dict[str, Any]] = []
    for i, url in enumerate(urls):
        role = f"node{i + 1}"
        row: dict[str, Any] = {"url": url, "role": role}
        if url not in reachable:
            errors.append(f"{role} not reachable at {url}")
            nodes.append(row)
            continue
        row["reachable"] = True
        try:
            st = _api(f"{url}/status", timeout=10)
            row["height"] = int(st.get("height", 0) or 0)
            row["peers"] = int(st.get("peers", st.get("peer_count", 0)) or 0)
            row["chain_id"] = int(st.get("chain_id", 0) or 0)
            row["deployment_mode"] = st.get("deployment_mode")
            row["head_hash"] = st.get("head_hash")
            if row["chain_id"] != MAINNET_V1_CHAIN_ID:
                errors.append(f"{role} chain_id={row['chain_id']} expected {MAINNET_V1_CHAIN_ID}")
            if str(st.get("deployment_mode", "")).lower() != "prod":
                warnings.append(f"{role} deployment_mode={st.get('deployment_mode')!r} expected prod")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{role} /status: {exc}")

        if deep and url in reachable:
            try:
                sec = _api(f"{url}/p2p/security", timeout=12)
                tls = sec.get("tls") or {}
                row["p2p_tls_enabled"] = bool(tls.get("enabled"))
                row["p2p_tls_ready"] = bool(tls.get("ready"))
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
                pass
            try:
                harness = _api(f"{url}/chain/consistency/harness?quick=1&peer_timeout=5", timeout=25)
                row["harness_healthy"] = bool(harness.get("harness_healthy"))
                row["tip_state_aligned"] = bool(harness.get("tip_state_aligned"))
                row["state_root"] = harness.get("live_state_root")
                if not row["harness_healthy"]:
                    errors.append(f"{role} harness unhealthy")
                if not row["tip_state_aligned"]:
                    errors.append(f"{role} tip_state not aligned")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                warnings.append(f"{role} harness: {exc}")
            try:
                topo = _api(f"{url}/p2p/topology", timeout=12)
                row["topology_healthy"] = bool(topo.get("topology_healthy"))
                row["peer_count"] = int(topo.get("peer_count", 0) or 0)
                if row["peer_count"] < 1 and len(reachable) >= 2:
                    warnings.append(f"{role} peer_count={row['peer_count']}")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                warnings.append(f"{role} topology: {exc}")
        nodes.append(row)

    if len(reachable) >= 2:
        align = _mesh_alignment_errors(nodes)
        attempt = 0
        while align and attempt < ALIGN_STATUS_RETRIES:
            time.sleep(ALIGN_STATUS_SLEEP_SEC)
            for row in nodes:
                if not row.get("reachable"):
                    continue
                try:
                    _refresh_status_fields(str(row.get("url") or ""), row)
                except (
                    urllib.error.URLError,
                    TimeoutError,
                    OSError,
                    ValueError,
                    json.JSONDecodeError,
                ):
                    pass
            align = _mesh_alignment_errors(nodes)
            attempt += 1
        errors.extend(align)

    meta: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "chain_id": MAINNET_V1_CHAIN_ID,
        "nodes": nodes,
        "reachable": len(reachable),
        "expected": len(urls),
        "ready": not errors,
    }
    return errors, warnings, meta


def write_report(errors: list[str], warnings: list[str], meta: dict[str, Any]) -> Path:
    out = ROOT / "logs" / "prod_mesh_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ok": not errors, "errors": errors, "warnings": warnings, **meta}
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify prod 3-node mesh (chain 778888)")
    parser.add_argument("--wait", type=int, default=0, help="Seconds to wait for all nodes")
    parser.add_argument("--quick", action="store_true", help="Skip harness/topology deep checks")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    errors, warnings, meta = verify_prod_mesh_probe(wait_sec=args.wait, deep=not args.quick)
    report = write_report(errors, warnings, meta)

    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors, "warnings": warnings, "report": str(report), **meta}, indent=2))
    else:
        print("=" * 60)
        print("PROD MESH PROBE (chain 778888)")
        print("=" * 60)
        if errors:
            print("RESULT: FAIL")
            for err in errors:
                print(f"  - {err}")
        else:
            print("RESULT: OK")
        for warn in warnings:
            print(f"  WARN: {warn}")
        print(f"Report: {report}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
