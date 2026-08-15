#!/usr/bin/env python3
"""Verify Profile F experimental R&D waves (local, no soak / no prod mesh).

Runs the same unit suites + lab scripts as `.github/workflows/experimental-rd.yml`.

Usage (from repo root):
  python scripts/verify_experimental_rd.py
  python scripts/verify_experimental_rd.py --labs-only
  python scripts/verify_experimental_rd.py --unit-only

Exit 0 = all steps PASS.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

UNIT_TESTS = [
    "tests/unit/test_evm_rpc_compat.py",
    "tests/unit/test_evm_nested_returndata.py",
    "tests/unit/test_evm_nested_staticcall.py",
    "tests/unit/test_evm_precompiles.py",
    "tests/unit/test_long_range_ws.py",
    "tests/unit/test_long_range_wave2.py",
    "tests/unit/test_long_range_wave3.py",
    "tests/unit/test_libp2p_adapter.py",
    "tests/unit/test_libp2p_wire_bridge.py",
    "tests/unit/test_libp2p_swarm_lab.py",
    "tests/unit/test_dual_stack.py",
    "tests/unit/test_prod_mesh_feature_freeze.py",
    "tests/unit/test_cargo_test_abs_native.py",
]

LABS = [
    "scripts/long_range_lab.py",
    "scripts/evm_precompile_lab.py",
    "scripts/libp2p_lab_smoke.py",
    "scripts/libp2p_two_node_lab.py",
    "scripts/libp2p_swarm_lab.py",
    "scripts/libp2p_three_node_lab.py",
    "scripts/libp2p_reqresp_lab.py",
    "scripts/libp2p_relay_lab.py",
    "scripts/libp2p_discovery_lab.py",
    "scripts/libp2p_identify_lab.py",
    "scripts/libp2p_mixed_dual_stack_lab.py",
    # ADR 0019 rust labs are opt-in (needs maturin --features libp2p); run via
    # CI job rd-libp2p-rust or package_libp2p_evidence.py:
    #   scripts/libp2p_rust_two_node_lab.py
    #   scripts/libp2p_rust_wire_lab.py
    #   scripts/libp2p_rust_three_node_lab.py
    #   scripts/libp2p_rust_soak_lab.py
]


def _run(cmd: list[str], *, label: str) -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return False, 0.0, str(exc)
    elapsed = time.perf_counter() - t0
    out = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0
    return ok, elapsed, out


def _safe_print(text: str) -> None:
    """Avoid Windows cp1251 crashes on lab unicode."""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.buffer.write((text + "\n").encode(enc, errors="replace"))
    sys.stdout.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--unit-only", action="store_true", help="pytest suites only")
    ap.add_argument("--labs-only", action="store_true", help="lab scripts only")
    ap.add_argument("-q", "--quiet", action="store_true", help="less pytest chatter")
    args = ap.parse_args()
    if args.unit_only and args.labs_only:
        print("FAIL: choose at most one of --unit-only / --labs-only")
        return 2

    py = sys.executable
    steps: list[tuple[str, list[str]]] = []
    if not args.labs_only:
        pytest_flags = ["-q"] if args.quiet else ["-q", "--tb=line"]
        steps.append(
            (
                "unit tests (Profile F)",
                [py, "-m", "pytest", *pytest_flags, *UNIT_TESTS],
            )
        )
    if not args.unit_only:
        for lab in LABS:
            steps.append((lab, [py, str(ROOT / lab)]))

    _safe_print("Experimental R&D verify")
    _safe_print(f"  root: {ROOT}")
    _safe_print(f"  python: {py}")
    _safe_print(f"  steps: {len(steps)}")
    _safe_print("-" * 60)

    failed: list[str] = []
    for label, cmd in steps:
        ok, elapsed, out = _run(cmd, label=label)
        status = "PASS" if ok else "FAIL"
        _safe_print(f"[{status}] {label}  ({elapsed:.1f}s)")
        if not ok:
            failed.append(label)
            # Show last ~40 lines of output for diagnosis
            lines = [ln for ln in out.splitlines() if ln.strip()]
            tail = lines[-40:] if len(lines) > 40 else lines
            for ln in tail:
                _safe_print(f"    {ln}")
        elif not args.quiet and label.startswith("scripts/"):
            for ln in out.splitlines():
                if ln.startswith("OK:") or ln.startswith("  "):
                    _safe_print(f"    {ln}")

    _safe_print("-" * 60)
    if failed:
        _safe_print(f"FAIL: {len(failed)}/{len(steps)} step(s) failed:")
        for name in failed:
            _safe_print(f"  - {name}")
        return 1
    _safe_print(f"OK: all {len(steps)} experimental R&D checks PASS")
    _safe_print("  honesty: lab/R&D only - not tip proof / not prod libp2p mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
