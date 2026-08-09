#!/usr/bin/env python3
"""Verify ADR 0019 rust-libp2p work (Slices A–U) locally.

Checks abs_native libp2p feature, unit tests, and all rust labs.

Prereq (once):
  cd native/abs_native
  maturin build --release --features "pyo3/extension-module,libp2p"
  python -m pip install --force-reinstall --no-deps <wheel>

Usage (from Experimental repo root):
  python scripts/verify_adr0019_libp2p.py
  python scripts/verify_adr0019_libp2p.py --labs-only
  python scripts/verify_adr0019_libp2p.py --unit-only
  python scripts/verify_adr0019_libp2p.py --evidence   # also write docs/evidence/runs/libp2p-rd

Exit 0 = all selected steps PASS.
Honesty: lab/R&D only — not tip proof / not prod libp2p mesh.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

UNIT_TESTS = [
    "tests/unit/test_libp2p_adapter.py",
    "tests/unit/test_libp2p_wire_bridge.py",
    "tests/unit/test_libp2p_status_metrics.py",
    "tests/unit/test_libp2p_prometheus_export.py",
    "tests/unit/test_libp2p_swarm_lab.py",
    "tests/unit/test_dual_stack.py",
    "tests/unit/test_prod_mesh_feature_freeze.py",
]

# Slice A–U rust / dual-stack labs (order = dependency-friendly)
LABS = [
    ("A", "scripts/libp2p_rust_two_node_lab.py"),
    ("B", "scripts/libp2p_rust_wire_lab.py"),
    ("B", "scripts/libp2p_rust_three_node_lab.py"),
    ("C", "scripts/libp2p_rust_soak_lab.py"),
    ("D", "scripts/libp2p_mixed_dual_stack_lab.py"),
    ("E", "scripts/libp2p_rust_gossip_lab.py"),
    ("F", "scripts/libp2p_rust_identity_mdns_lab.py"),
    ("G", "scripts/libp2p_rust_kad_lab.py"),
    ("G", "scripts/libp2p_rust_abs_announce_lab.py"),
    ("H", "scripts/libp2p_rust_relay_limits_lab.py"),
    ("I", "scripts/libp2p_rust_blocklist_lab.py"),
    ("J", "scripts/libp2p_rust_status_surface_lab.py"),
    ("K", "scripts/libp2p_rust_mdns_toggle_lab.py"),
    ("L", "scripts/libp2p_rust_wire_timeout_lab.py"),
    ("M", "scripts/libp2p_rust_abs_wire_lab.py"),
    ("N", "scripts/libp2p_rust_autonat_dcutr_lab.py"),
    ("O", "scripts/libp2p_rust_bootstrap_lab.py"),
    ("P", "scripts/libp2p_rust_reconnect_lab.py"),
    ("Q", "scripts/libp2p_rust_peer_score_lab.py"),
    ("R", "scripts/libp2p_rust_ping_lab.py"),
    ("S", "scripts/libp2p_rust_score_autoblock_lab.py"),
    ("T", "scripts/libp2p_rust_peerstore_lab.py"),
    ("U", "scripts/libp2p_rust_peerstore_reconnect_lab.py"),
    ("V", "scripts/libp2p_rust_idle_timeout_lab.py"),
    ("W", "scripts/libp2p_rust_ipv6_lab.py"),
    ("X", "scripts/libp2p_rust_rendezvous_lab.py"),
    ("Y", "scripts/libp2p_rust_dns_lab.py"),
    ("Z", "scripts/libp2p_rust_prometheus_lab.py"),
    ("AA", "scripts/libp2p_rust_connection_manager_lab.py"),
    ("AB", "scripts/libp2p_rust_quic_lab.py"),
    ("AC", "scripts/libp2p_rust_websocket_lab.py"),
    ("AD", "scripts/libp2p_rust_upnp_lab.py"),
    ("AE", "scripts/libp2p_rust_allowlist_lab.py"),
    ("AF", "scripts/libp2p_rust_bandwidth_lab.py"),
    ("AG", "scripts/libp2p_rust_external_addr_lab.py"),
    ("AH", "scripts/libp2p_rust_connection_lifecycle_lab.py"),
    ("AI", "scripts/libp2p_rust_connection_close_cause_lab.py"),
    ("AJ", "scripts/libp2p_rust_listener_lifecycle_lab.py"),
    ("AK", "scripts/libp2p_rust_connection_attempt_lab.py"),
    ("AL", "scripts/libp2p_rust_identify_events_lab.py"),
    ("AM", "scripts/libp2p_rust_gossip_subscription_lab.py"),
    ("AN", "scripts/libp2p_rust_kad_events_lab.py"),
    ("AO", "scripts/libp2p_rust_wire_rr_events_lab.py"),
    ("AP", "scripts/libp2p_rust_relay_events_lab.py"),
    ("AQ", "scripts/libp2p_rust_rendezvous_events_lab.py"),
    ("AR", "scripts/libp2p_rust_autonat_events_lab.py"),
    ("AS", "scripts/libp2p_rust_mdns_events_lab.py"),
    ("AT", "scripts/libp2p_rust_relay_client_events_lab.py"),
    ("AU", "scripts/libp2p_rust_dial_fail_events_lab.py"),
    ("AV", "scripts/libp2p_rust_incoming_fail_events_lab.py"),
    ("AW", "scripts/libp2p_rust_dial_deny_events_lab.py"),
    ("AX", "scripts/libp2p_rust_deny_cause_events_lab.py"),
    ("AY", "scripts/libp2p_rust_ping_fail_events_lab.py"),
    ("AZ", "scripts/libp2p_rust_wire_fail_events_lab.py"),
    ("BA", "scripts/libp2p_rust_gossip_validation_lab.py"),
    ("BB", "scripts/libp2p_rust_wire_omit_response_lab.py"),
    ("BC", "scripts/libp2p_rust_identify_push_lab.py"),
    ("BD", "scripts/libp2p_rust_identify_interval_lab.py"),
    ("BE", "scripts/libp2p_rust_peerstore_remove_lab.py"),
    ("BF", "scripts/libp2p_rust_peerstore_allow_learn_lab.py"),
    ("BG", "scripts/libp2p_rust_identify_observed_addr_lab.py"),
    ("BH", "scripts/libp2p_rust_bootstrap_remove_lab.py"),
]


def _print(text: str) -> None:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.buffer.write((text + "\n").encode(enc, errors="replace"))
    sys.stdout.flush()


def _run(cmd: list[str]) -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        return False, 180.0, f"TIMEOUT: {exc}"
    except OSError as exc:
        return False, 0.0, str(exc)
    elapsed = time.perf_counter() - t0
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, elapsed, out


def _check_native() -> tuple[bool, str]:
    try:
        import abs_native  # type: ignore
    except Exception as exc:
        return False, f"abs_native import failed: {exc}"
    avail = bool(getattr(abs_native, "libp2p_available", lambda: False)())
    if not avail:
        return (
            False,
            "libp2p_available() is False — rebuild with "
            'maturin build --release --features "pyo3/extension-module,libp2p"',
        )
    wire = str(getattr(abs_native, "ABS_WIRE_PROTOCOL", ""))
    gossip = str(getattr(abs_native, "ABS_GOSSIP_BLOCKS_TOPIC", ""))
    kad = str(getattr(abs_native, "ABS_KAD_PROTOCOL", ""))
    return True, f"ok wire={wire} gossip={gossip} kad={kad}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labs-only", action="store_true")
    ap.add_argument("--unit-only", action="store_true")
    ap.add_argument(
        "--evidence",
        action="store_true",
        help="after PASS, run package_libp2p_evidence.py --skip-run is NOT used; "
        "re-packs from freshly written lab logs in this run via package script",
    )
    ap.add_argument("-q", "--quiet", action="store_true", help="less lab stdout")
    args = ap.parse_args()

    rows: list[tuple[str, bool, float, str]] = []

    _print("=== ADR 0019 verify (Experimental) ===")
    _print(f"root: {ROOT}")

    ok_n, detail_n = _check_native()
    rows.append(("native_libp2p", ok_n, 0.0, detail_n))
    _print(f"[{'PASS' if ok_n else 'FAIL'}] native_libp2p — {detail_n}")
    if not ok_n and not args.unit_only:
        _print("Abort: rust labs need abs_native with Cargo feature libp2p.")
        return 1

    if not args.labs_only:
        cmd = [sys.executable, "-m", "pytest", "-q", *UNIT_TESTS]
        ok, elapsed, out = _run(cmd)
        tail = out.strip().splitlines()[-1] if out.strip() else ""
        rows.append(("unit_tests", ok, elapsed, tail))
        _print(f"[{'PASS' if ok else 'FAIL'}] unit_tests ({elapsed:.1f}s) {tail}")
        if not ok and not args.quiet:
            _print(out[-2000:] if len(out) > 2000 else out)

    if not args.unit_only:
        if not ok_n:
            return 1
        for slice_id, rel in LABS:
            label = f"slice_{slice_id}:{Path(rel).stem}"
            ok, elapsed, out = _run([sys.executable, str(ROOT / rel)])
            line = ""
            for ln in (out or "").splitlines():
                if ln.startswith("OK:") or ln.startswith("FAIL:"):
                    line = ln
            rows.append((label, ok, elapsed, line))
            _print(f"[{'PASS' if ok else 'FAIL'}] {label} ({elapsed:.1f}s) {line}")
            if not ok and not args.quiet:
                _print(out[-1500:] if len(out) > 1500 else out)

    if args.evidence and all(r[1] for r in rows):
        ok, elapsed, out = _run(
            [sys.executable, str(ROOT / "scripts" / "package_libp2p_evidence.py")]
        )
        rows.append(("evidence_pack", ok, elapsed, "see docs/evidence/runs/libp2p-rd"))
        _print(f"[{'PASS' if ok else 'FAIL'}] evidence_pack ({elapsed:.1f}s)")

    passed = sum(1 for _, ok, _, _ in rows if ok)
    failed = sum(1 for _, ok, _, _ in rows if not ok)
    _print("---")
    _print(f"summary: {passed} PASS, {failed} FAIL / {len(rows)} steps")
    _print("honesty: lab/R&D only — not tip proof / not prod TCP+TLS cutover")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
