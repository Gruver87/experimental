#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Operator self-check for Experimental prod-profile mesh.

Does NOT start 48h soak. Does NOT rebuild Docker. Does NOT claim mainnet.

Usage (from repo root)::

    python scripts/check_blockchain.py
    python scripts/check_blockchain.py --skip-tests
    python scripts/check_blockchain.py --skip-live
    python scripts/check_blockchain.py --pytest-all
    python scripts/check_blockchain.py --require-soak-48h

Windows::

    .\\scripts\\check_blockchain.ps1

Exit:
  0  every enabled step passed (soak is informational unless --require-soak-48h)
  1  a required step failed
  2  live mesh required but unreachable

Report: logs/check_blockchain.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "logs" / "check_blockchain.json"
SOAK_48H = ROOT / "logs" / "soak_report_48h_experimental.json"
SOAK_5H = ROOT / "logs" / "soak_report_5h_strict.json"

DEFAULT_UNIT = (
    "tests/unit/test_amount_units.py",
    "tests/unit/test_balance_write_path_unify.py",
    "tests/unit/test_rocks_store.py",
    "tests/unit/test_tip_safety_shadow.py",
    "tests/unit/test_p2p_dispatch.py",
    "tests/unit/test_verify_prod_mesh_probe.py",
    "tests/unit/test_soak_preflight.py",
    "tests/unit/test_silent_except_honesty.py",
    "tests/unit/test_check_blockchain.py",
    "tests/unit/test_transaction_from_dict.py",
)


def _banner(title: str) -> None:
    print()
    print("=" * 72)
    print(f" {title}")
    print("=" * 72)


def _run(cmd: list[str], *, timeout: int | None = None) -> int:
    print("$ " + " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT), timeout=timeout, check=False)
    return int(proc.returncode)


def read_soak_report(path: Path) -> dict[str, Any]:
    """Host-side soak honesty. Never upgrades a FAIL file to passed=true."""
    try:
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        rel = str(path)
    out: dict[str, Any] = {
        "path": rel,
        "exists": path.is_file(),
        "passed": False,
        "claim": "NOT_RUN",
    }
    if not path.is_file():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        out["claim"] = "UNREADABLE"
        out["error"] = str(exc)
        return out
    if not isinstance(data, dict):
        out["claim"] = "UNREADABLE"
        out["error"] = "soak report is not an object"
        return out
    # JSON true only. Never coerce missing/None to PASS.
    passed = data.get("passed") is True
    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    out.update(
        {
            "passed": passed,
            "claim": "PASS" if passed else "FAIL",
            "hours_elapsed": data.get("hours_elapsed"),
            "hours_requested": data.get("hours_requested"),
            "hard_fail_lines": counts.get("hard_fail_lines"),
            "strict": bool(data.get("strict")),
            "started_at": data.get("started_at"),
            "ended_at": data.get("ended_at"),
        }
    )
    if passed:
        # Defensive: a PASS file with hard_fails>0 is still FAIL.
        try:
            hf = int(counts.get("hard_fail_lines") or 0)
        except (TypeError, ValueError):
            hf = 1
        if hf > 0:
            out["passed"] = False
            out["claim"] = "FAIL"
            out["error"] = f"hard_fail_lines={hf} cannot be soak PASS"
    return out


def soak_honesty() -> dict[str, Any]:
    experimental_48h = read_soak_report(SOAK_48H)
    strict_5h = read_soak_report(SOAK_5H)
    return {
        "experimental_48h": experimental_48h,
        "strict_5h": strict_5h,
        "claim_48h_pass": bool(experimental_48h.get("passed")),
        "note": (
            "48h PASS requires this tree's soak_report_48h_experimental.json "
            "passed=true and hard_fails=0. Historical Hybrid 375d14f is a different tree."
        ),
    }


def _print_soak(block: dict[str, Any], label: str) -> None:
    claim = str(block.get("claim") or "NOT_RUN")
    color_ok = claim == "PASS"
    extra = ""
    if block.get("exists"):
        extra = (
            f" hours={block.get('hours_elapsed')} "
            f"hard_fails={block.get('hard_fail_lines')}"
        )
    print(f"  {label}: {claim}{extra}  ({block.get('path')})")
    if not color_ok and claim == "FAIL":
        print("    (honest FAIL — do not treat as PASS)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Self-check Experimental mesh + tests (does not start soak)"
    )
    ap.add_argument("--skip-live", action="store_true", help="Skip :18180-:18182 probe")
    ap.add_argument("--skip-tests", action="store_true", help="Skip unit pytest slice")
    ap.add_argument("--skip-gate", action="store_true", help="Skip industrial_gate.py")
    ap.add_argument(
        "--pytest-all",
        action="store_true",
        help="Run the full tests/ tree instead of the default unit slice",
    )
    ap.add_argument(
        "--require-soak-48h",
        action="store_true",
        help="Fail if Experimental 48h soak report is not passed=true",
    )
    ap.add_argument("--wait", type=int, default=0, help="Seconds to wait for mesh ready")
    args = ap.parse_args()

    started = time.time()
    steps: list[dict[str, Any]] = []
    errors: list[str] = []
    mesh_down = False

    _banner("CHECK BLOCKCHAIN  (Experimental)")
    print(f" Repo: {ROOT}")
    print(" Honesty: PASS != public mainnet. Soak is NOT started.")
    print(" Mesh: http://127.0.0.1:18180 18181 18182")

    py = sys.executable

    if not args.skip_live:
        _banner("1) live prod mesh probe")
        cmd = [py, "scripts/verify_prod_mesh_probe.py", "--quick"]
        if args.wait > 0:
            cmd += ["--wait", str(args.wait)]
        rc = _run(cmd)
        steps.append({"name": "mesh_probe", "rc": rc})
        if rc != 0:
            errors.append("live mesh probe FAIL")
            mesh_down = True
            print("  mesh down? start (does not start soak):")
            print("    .\\scripts\\docker_prod_3node.ps1 -KeepVolumes")
            print("    .\\scripts\\probe_prod_mesh.ps1 -Quick")
        else:
            print("OK: mesh probe")

    if not args.skip_tests:
        _banner("2) unit tests")
        if args.pytest_all:
            cmd = [py, "-m", "pytest", "-q", "--tb=line", "tests/"]
        else:
            cmd = [py, "-m", "pytest", "-q", "--tb=line", *DEFAULT_UNIT]
        rc = _run(cmd)
        steps.append({"name": "pytest", "rc": rc})
        if rc != 0:
            errors.append("pytest FAIL")
        else:
            print("OK: unit tests")

    if not args.skip_gate:
        _banner("3) industrial_gate")
        # Do NOT pass --min-soak-hours: last Experimental 48h is FAIL and must stay FAIL.
        rc = _run([py, "scripts/industrial_gate.py"])
        steps.append({"name": "industrial_gate", "rc": rc})
        if rc != 0:
            errors.append("industrial_gate FAIL")
        else:
            print("OK: industrial_gate (org-warnings may still print)")

    _banner("4) soak honesty (read-only, soak not started)")
    soak = soak_honesty()
    _print_soak(soak["experimental_48h"], "48h Experimental")
    _print_soak(soak["strict_5h"], "5h STRICT")
    print(f"  {soak['note']}")
    steps.append(
        {
            "name": "soak_honesty",
            "rc": 0,
            "claim_48h_pass": soak["claim_48h_pass"],
        }
    )
    if args.require_soak_48h and not soak["claim_48h_pass"]:
        errors.append("48h Experimental soak is not PASS")
        steps[-1]["rc"] = 1

    ok = not errors
    elapsed = round(time.time() - started, 2)
    report = {
        "script": "check_blockchain.py",
        "ok": ok,
        "errors": errors,
        "elapsed_sec": elapsed,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "soak": soak,
        "honesty": [
            "PASS is not public mainnet",
            "this script does not start soak",
            "this script does not rebuild Docker",
            "industrial_gate is not --min-soak-hours 48 (last Experimental 48h is FAIL)",
        ],
        "rerun": [
            "python scripts/check_blockchain.py",
            "python scripts/verify_prod_mesh_probe.py --quick",
            "python scripts/industrial_gate.py",
            "python -m pytest -q " + " ".join(DEFAULT_UNIT),
        ],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    _banner("RESULT")
    if ok:
        soak_word = "SOAK_48H_PASS" if soak["claim_48h_pass"] else "SOAK_48H_NOT_PASS"
        print(f"RESULT: OK  {soak_word}")
        print(f"Report: {REPORT_PATH}")
        return 0
    print("RESULT: FAIL")
    for err in errors:
        print(f"  - {err}")
    print(f"Report: {REPORT_PATH}")
    if mesh_down and all(e == "live mesh probe FAIL" for e in errors):
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
