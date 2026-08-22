#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preflight checks before starting a long prod-mesh soak (does NOT start soak)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROD_MESH_URLS = (
    "http://127.0.0.1:18180",
    "http://127.0.0.1:18181",
    "http://127.0.0.1:18182",
)


def _git_cmd(*args: str) -> str:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _git_tag() -> str:
    return _git_cmd("describe", "--tags", "--abbrev=0") or "unknown"


def _git_sha() -> str:
    return _git_cmd("rev-parse", "HEAD") or "unknown"


def _git_dirty() -> bool:
    return bool(_git_cmd("status", "--porcelain"))


def run_soak_preflight(
    *,
    hours: int = 48,
    interval_sec: int = 300,
    require_p2p_tls: bool = False,
    require_wire_probe: bool = False,
    require_libp2p: bool = False,
) -> tuple[list[str], list[str], dict]:
    import importlib.util

    vp_path = ROOT / "scripts" / "verify_p2p_ci.py"
    spec = importlib.util.spec_from_file_location("verify_p2p_ci", vp_path)
    vp = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(vp)
    _api = vp._api
    _consistency_harness = vp._consistency_harness
    _fetch_p2p_security = vp._fetch_p2p_security
    _probe_health = vp._probe_health
    verify_p2p_security_mesh = vp.verify_p2p_security_mesh

    errors: list[str] = []
    warnings: list[str] = []
    urls = list(PROD_MESH_URLS)
    nodes: list[dict] = []

    active_path = ROOT / "logs" / "soak_active.json"
    if active_path.is_file():
        try:
            active = json.loads(active_path.read_text(encoding="utf-8"))
            warnings.append(
                "soak_active.json present — another soak may be running "
                f"(started {active.get('started_at', '?')})"
            )
        except (OSError, json.JSONDecodeError):
            warnings.append("soak_active.json present but unreadable")

    for i, url in enumerate(urls, start=1):
        row = {"url": url, "reachable": False}
        if not _probe_health(url, timeout=5):
            errors.append(f"node{i} not reachable at {url}")
            nodes.append(row)
            continue
        row["reachable"] = True
        try:
            t0 = time.perf_counter()
            st = _api(f"{url}/status", timeout=12)
            status_ms = (time.perf_counter() - t0) * 1000.0
            row["status_ms"] = round(status_ms, 1)
            if status_ms > 2000:
                msg = (
                    f"node{i} /status {status_ms:.0f}ms "
                    "(need <2000ms for 48h health_watch)"
                )
                if require_wire_probe:
                    errors.append(msg)
                else:
                    warnings.append(msg)
            row["height"] = int(st.get("height", 0) or 0)
            row["peers"] = int(st.get("peers", st.get("peer_count", 0)) or 0)
            row["deployment_mode"] = st.get("deployment_mode")
            row["p2p_sync_status"] = st.get("p2p_sync_status")
            if str(st.get("deployment_mode", "")).lower() != "prod":
                warnings.append(f"node{i} deployment_mode={st.get('deployment_mode')!r}")
            if int(row.get("peers") or 0) < 2:
                msg = f"node{i} peers={row.get('peers')} (need >=2 for 48h mesh)"
                if require_wire_probe:
                    errors.append(msg)
                else:
                    warnings.append(msg)
            consist = st.get("state_consistent")
            if consist is False:
                msg = f"node{i} state_consistent=false"
                if require_wire_probe:
                    errors.append(msg)
                else:
                    warnings.append(msg)
            lib = dict(st.get("libp2p") or {})
            row["libp2p_active"] = bool(lib.get("active"))
            row["libp2p_rust_backend"] = bool(lib.get("rust_backend"))
            row["libp2p_honesty"] = str(lib.get("honesty") or "")
            if require_libp2p:
                if not lib.get("active") or not lib.get("rust_backend"):
                    errors.append(
                        f"node{i} libp2p not live "
                        f"(active={lib.get('active')} rust_backend={lib.get('rust_backend')})"
                    )
                honesty = str(lib.get("honesty") or "")
                if "lab_not_prod_mesh" in honesty:
                    errors.append(f"node{i} libp2p honesty still lab: {honesty}")
        except OSError as exc:
            errors.append(f"node{i} /status: {exc}")
        try:
            sec, source = _fetch_p2p_security(url)
            row["p2p_security_source"] = source
            row["rate_limit_per_sec"] = int((sec or {}).get("rate_limit_per_sec", 0) or 0)
            tls = (sec or {}).get("tls") or {}
            row["p2p_tls_enabled"] = bool(tls.get("enabled"))
            row["p2p_tls_ready"] = bool(tls.get("ready"))
            if tls.get("enabled") and not tls.get("ready"):
                msg = f"node{i} P2P TLS enabled but not ready"
                if require_p2p_tls:
                    errors.append(msg)
                else:
                    warnings.append(msg)
            if require_p2p_tls and not tls.get("enabled"):
                errors.append(f"node{i} P2P TLS not enabled (use docker_prod_3node.ps1 -P2pTls)")
        except OSError as exc:
            warnings.append(f"node{i} p2p security: {exc}")
        nodes.append(row)

    reachable = [u for u in urls if _probe_health(u, timeout=3)]
    if len(reachable) >= 2:
        align_errors: list[str] = ["start"]
        for attempt in range(4):
            if attempt:
                time.sleep(3.0)
            align_errors = []
            heights = [n.get("height", 0) for n in nodes if n.get("reachable")]
            if heights and max(heights) - min(heights) > 1:
                align_errors.append(f"height spread across mesh: {heights}")
            heads = []
            for url in reachable:
                try:
                    st = _api(f"{url}/status", timeout=8)
                    heads.append(str(st.get("head_hash") or "").lower())
                    # Keep node rows honest after a retry (mining-window race).
                    for row in nodes:
                        if row.get("url") == url:
                            row["height"] = int(st.get("height", 0) or 0)
                            row["head_hash"] = st.get("head_hash")
                except OSError:
                    pass
            if heads and len(set(h for h in heads if h)) > 1:
                align_errors.append("head hash mismatch across reachable nodes")
            if not align_errors:
                break
        errors.extend(align_errors)

    if len(reachable) == len(urls):
        sec_rc = verify_p2p_security_mesh(urls)
        if sec_rc != 0:
            errors.append("verify_p2p_security_mesh failed (see stdout above)")

    # Same soft set as verify_p2p_ci mesh harness: tip/wire/state lag is not a
    # hard soak blocker when heights + peers already agree across the mesh.
    _SOFT_HARNESS = frozenset(
        {"tip_state_aligned", "peer_probe_ok", "p2p_state_consistent"}
    )

    harness_urls = list(reachable) if require_wire_probe else reachable[:1]
    for url in harness_urls:
        attempts = 3 if require_wire_probe else 1
        last_exc: OSError | None = None
        harness: dict = {}
        for attempt in range(attempts):
            try:
                if require_wire_probe:
                    # Full wire probe (not prod-mesh quick/3s). Quick timeout was
                    # painting peer_probe_error=timeout on an otherwise healthy harness.
                    harness = _consistency_harness(
                        url, quick=False, peer_timeout=8.0
                    )
                else:
                    harness = _consistency_harness(url)
                last_exc = None
            except OSError as exc:
                last_exc = exc
                harness = {}
            failed = list(harness.get("failed_checks") or [])
            healthy = bool(harness.get("harness_healthy"))
            probe_err = harness.get("peer_probe_error")
            retryable = (not healthy) or bool(probe_err) or last_exc is not None
            if not retryable or attempt + 1 >= attempts:
                break
            time.sleep(1.0)
        if last_exc is not None and not harness:
            errors.append(f"harness {url}: {last_exc}")
            continue
        failed = list(harness.get("failed_checks") or [])
        if not harness.get("harness_healthy"):
            hard = failed if require_wire_probe else [f for f in failed if f not in _SOFT_HARNESS]
            if hard:
                errors.append(f"harness {url}: {failed}")
            else:
                warnings.append(
                    f"harness soft fails (tolerated): {failed} "
                    "(tip/wire/state lag under tip-v2 forge load)"
                )
        elif require_wire_probe and harness.get("peer_probe_error"):
            # Full harness + still-healthy: leftover timeout field is a WARN, not
            # a prepare hard fail (48h scores harness flake as WARN).
            warnings.append(
                f"harness {url} peer_probe_error={harness.get('peer_probe_error')} "
                "(harness_healthy; not a soak hard fail)"
            )

    if reachable:
        try:
            topo = _api(f"{reachable[0]}/p2p/topology", timeout=12)
            if int(topo.get("peer_count", 0) or 0) < 2:
                msg = (
                    f"leader peer_count={topo.get('peer_count')} "
                    "(need >=2 before 48h soak)"
                )
                if require_wire_probe:
                    errors.append(msg)
                else:
                    warnings.append(msg)
        except OSError as exc:
            warnings.append(f"topology: {exc}")

    tag = _git_tag()
    start_cmd = (
        f".\\scripts\\start_soak_prod_mesh_48h.ps1 -Hours {hours} "
        f"-IntervalSec {interval_sec}"
    )
    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ready": not errors,
        "hours_planned": hours,
        "interval_sec": interval_sec,
        "git_tag": tag,
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "nodes": nodes,
        "start_command": start_cmd,
        "after_complete": (
            f"python scripts/industrial_gate.py --min-soak-hours {hours}"
        ),
        "note": (
            "Experimental 48h default scoring. Not Hybrid historical PASS. "
            "Not 5h STRICT. Run preflight again immediately before starting soak."
        ),
        "require_p2p_tls": require_p2p_tls,
        "require_libp2p": require_libp2p,
        "require_wire_probe": require_wire_probe,
    }
    return errors, warnings, meta


def write_report(errors: list[str], warnings: list[str], meta: dict) -> Path:
    out = ROOT / "logs" / "soak_preflight.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        **meta,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Prod mesh soak preflight (no soak start)")
    parser.add_argument("--hours", type=int, default=48, help="Planned soak duration")
    parser.add_argument("--interval-sec", type=int, default=300, help="Planned poll interval")
    parser.add_argument(
        "--require-p2p-tls",
        action="store_true",
        help="Fail if prod mesh P2P wire TLS is not enabled and ready on all nodes",
    )
    parser.add_argument(
        "--require-wire-probe",
        action="store_true",
        help="Fail if any node harness is unhealthy or peers<2 (48h prep)",
    )
    parser.add_argument(
        "--require-libp2p",
        action="store_true",
        help="Fail if rust-libp2p swarm is not active on all nodes (ADR 0020)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    args = parser.parse_args()

    errors, warnings, meta = run_soak_preflight(
        hours=args.hours,
        interval_sec=args.interval_sec,
        require_p2p_tls=args.require_p2p_tls,
        require_wire_probe=args.require_wire_probe,
        require_libp2p=args.require_libp2p,
    )
    report_path = write_report(errors, warnings, meta)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": not errors,
                    "errors": errors,
                    "warnings": warnings,
                    "report": str(report_path),
                    **meta,
                },
                indent=2,
            )
        )
    else:
        print("=" * 60)
        print("SOAK PREFLIGHT (prod mesh :18180-:18182)")
        print("=" * 60)
        if errors:
            print("RESULT: NOT READY")
            for err in errors:
                print(f"  - {err}")
        else:
            print("RESULT: READY for soak")
        for warn in warnings:
            print(f"  WARN: {warn}")
        print(f"Report: {report_path}")
        if not errors:
            print("")
            print("When you are ready to start (not now unless intended):")
            print(f"  {meta['start_command']}")
            print("")
            print("After soak completes:")
            print(f"  {meta['after_complete']}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
