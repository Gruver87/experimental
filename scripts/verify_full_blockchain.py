#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deep Experimental blockchain verification (host + live 3-node mesh).

Does NOT start 48h soak. Does NOT rebuild Docker. Does NOT claim mainnet.

Runs every industrial check it can, then prints a full scoreboard.
A failed step does not skip the rest (scan-all). Exit 1 if any required
step failed. Exit 2 if the only failures are live mesh unreachable.

Usage (repo root)::

    python scripts/verify_full_blockchain.py --hard
    python scripts/verify_full_blockchain.py
    python scripts/verify_full_blockchain.py --skip-live
    python scripts/verify_full_blockchain.py --skip-cargo --skip-native
    python scripts/verify_full_blockchain.py --quick-pytest

Windows::

    .\\scripts\\verify_hard_all.ps1
    .\\scripts\\verify_full_blockchain.ps1 -Hard
    .\\scripts\\verify_full_blockchain.ps1 -SkipLive
    .\\scripts\\verify_full_blockchain.ps1 -Help

Report: logs/verify_full_blockchain.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "logs" / "verify_full_blockchain.json"
MESH = (
    ("miner", "http://127.0.0.1:18180"),
    ("full1", "http://127.0.0.1:18181"),
    ("full2", "http://127.0.0.1:18182"),
)
CONTAINER = "abs-prod-mesh3-node1-1"
STATUS_SLO_MS = 2000.0
STATUS_HARD_MS = 8000.0

QUICK_PYTEST = (
    "tests/unit/test_amount_units.py",
    "tests/unit/test_balance_write_path_unify.py",
    "tests/unit/test_rocks_store.py",
    "tests/unit/test_api.py",
    "tests/unit/test_prod_compose.py",
    "tests/unit/test_prod_config.py",
    "tests/unit/test_p2p_class_rate.py",
    "tests/unit/test_p2p_dispatch.py",
    "tests/unit/test_silent_except_honesty.py",
    "tests/unit/test_consistency_harness_probe.py",
    "tests/unit/test_v1351_p2p_import_offload.py",
    "tests/unit/test_v1352_chain_apply_queue.py",
    "tests/unit/test_committed_state_root.py",
    "tests/unit/test_check_blockchain.py",
    "tests/unit/test_verify_p2p_skip_policy.py",
    "tests/unit/test_soak_preflight.py",
    "tests/unit/test_verify_prod_mesh_probe.py",
    "tests/unit/test_tip_safety_shadow.py",
    "tests/unit/test_transaction_from_dict.py",
)


def _banner(title: str) -> None:
    print()
    print("=" * 72)
    print(f" {title}")
    print("=" * 72)


def _run(cmd: list[str], *, timeout: int | None = None) -> int:
    print("$ " + " ".join(cmd), flush=True)
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT after {timeout}s", flush=True)
        return 124
    except FileNotFoundError as exc:
        print(f"MISSING: {exc}", flush=True)
        return 127
    return int(proc.returncode)


def _load_check_blockchain():
    path = ROOT / "scripts" / "check_blockchain.py"
    spec = importlib.util.spec_from_file_location("check_blockchain", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _bind_prod_smoke_wallet() -> str:
    """Point verify_p2p_ci at the local mesh miner wallet (signed tx; no auto_sign)."""
    env = os.environ.get("PROD_SMOKE_WALLET_PATH", "").strip()
    default = ROOT / "data" / "prod_mesh" / "wallets" / "validator-1.wallet.json"
    path = env if env else (str(default) if default.is_file() else "")
    if path:
        os.environ["PROD_SMOKE_WALLET_PATH"] = path
        print(f"PROD_SMOKE_WALLET_PATH={path}")
        return path
    print(
        "WARN: no prod smoke wallet; verify_p2p_ci signed tx will FAIL "
        f"(expected {default})"
    )
    return ""


def _status_slo() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    worst = 0.0
    reachable = 0
    hard = False
    slo_fail = False
    for role, base in MESH:
        url = f"{base}/status"
        row: dict[str, Any] = {"role": role, "url": url}
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                body = json.loads(resp.read().decode())
            ms = (time.perf_counter() - t0) * 1000.0
            reachable += 1
            row["ms"] = round(ms, 1)
            row["height"] = body.get("height")
            row["ok"] = True
            worst = max(worst, ms)
            if ms > STATUS_HARD_MS:
                hard = True
            elif ms > STATUS_SLO_MS:
                slo_fail = True
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            row["ok"] = False
            row["error"] = str(exc)
        rows.append(row)
        print(
            f"  {role:<6} {row.get('ms', 'DOWN'):>8}  height={row.get('height', '-')}"
        )
    rc = 0
    if reachable == 0:
        rc = 2
    elif hard or slo_fail:
        rc = 1
    return {
        "rc": rc,
        "rows": rows,
        "worst_ms": round(worst, 1),
        "reachable": reachable,
        "slo_ms": STATUS_SLO_MS,
        "hard_ms": STATUS_HARD_MS,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Deep Experimental blockchain check (does not start soak)"
    )
    ap.add_argument(
        "--hard",
        action="store_true",
        help="Fail-closed full project: no skip flags, cargo required, live mesh required, baked root required. Does not start soak.",
    )
    ap.add_argument("--skip-live", action="store_true")
    ap.add_argument("--skip-native", action="store_true")
    ap.add_argument("--skip-cargo", action="store_true")
    ap.add_argument("--skip-pytest", action="store_true")
    ap.add_argument(
        "--quick-pytest",
        action="store_true",
        help="Industrial unit slice instead of full tests/",
    )
    ap.add_argument("--skip-gate", action="store_true")
    ap.add_argument("--require-soak-48h", action="store_true")
    ap.add_argument("--require-baked-root", action="store_true")
    ap.add_argument("--pytest-timeout", type=int, default=1200)
    ap.add_argument("--p2p-wait", type=int, default=90)
    args = ap.parse_args()

    if args.hard:
        forbidden = [
            name
            for name, on in (
                ("--skip-live", args.skip_live),
                ("--skip-native", args.skip_native),
                ("--skip-cargo", args.skip_cargo),
                ("--skip-pytest", args.skip_pytest),
                ("--quick-pytest", args.quick_pytest),
                ("--skip-gate", args.skip_gate),
            )
            if on
        ]
        if forbidden:
            print("FAIL: --hard refuses skip flags: " + ", ".join(forbidden))
            print("  Use .\\scripts\\verify_hard_all.ps1 with no extra switches.")
            return 1
        args.require_baked_root = True
        if int(args.pytest_timeout) < 1800:
            args.pytest_timeout = 1800
        if int(args.p2p_wait) < 120:
            args.p2p_wait = 120

    py = sys.executable
    started = time.time()
    steps: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    mesh_down = False

    _banner("VERIFY FULL BLOCKCHAIN  (Experimental)")
    print(f" Repo: {ROOT}")
    print(" Honesty: PASS != public mainnet. Soak is NOT started. Docker is NOT rebuilt.")
    print(" Mesh: :18180 miner  :18181 full1  :18182 full2  chain 778888")
    if args.hard:
        print(" Mode: HARD fail-closed (no skips; cargo+mesh+baked root required; soak NOT started)")
    else:
        print(" Mode: scan-all (later steps still run after a FAIL)")

    def step(
        name: str,
        cmd: list[str] | None,
        *,
        timeout: int | None = None,
        required: bool = True,
        runner=None,
    ) -> int:
        _banner(name)
        if runner is not None:
            payload = runner()
            rc = int(payload.get("rc", 1) if isinstance(payload, dict) else int(payload))
            rec: dict[str, Any] = {"name": name, "rc": rc, "required": required}
            if isinstance(payload, dict):
                rec["detail"] = {
                    k: v for k, v in payload.items() if k not in ("rc",)
                }
            steps.append(rec)
        else:
            assert cmd is not None
            rc = _run(cmd, timeout=timeout)
            steps.append({"name": name, "rc": rc, "required": required, "cmd": cmd})
        if rc == 0:
            print(f"OK: {name}")
            return rc
        msg = f"{name} FAIL rc={rc}"
        if required:
            errors.append(msg)
            print(f"FAIL: {msg}")
        else:
            warnings.append(msg)
            print(f"WARN: {msg}")
        return rc

    step("python --version", [py, "--version"])

    if not args.skip_native:
        step(
            "native crypto self-test",
            [
                py,
                "-c",
                "from crypto import native; st=native.native_crypto_status(required=True); "
                "assert st['available'] and st['self_test'], st; print('OK native:', st)",
            ],
        )

    if not args.skip_cargo:
        cargo = shutil.which("cargo")
        if cargo is None:
            if args.hard:
                errors.append("cargo not on PATH (required by --hard)")
                print("FAIL: cargo not on PATH — required by --hard")
                steps.append(
                    {
                        "name": "cargo test abs_native",
                        "rc": 127,
                        "required": True,
                        "skipped": False,
                    }
                )
            else:
                warnings.append("cargo not on PATH; skipped abs_native cargo test")
                print("WARN: cargo not on PATH — skip native cargo test")
                steps.append(
                    {
                        "name": "cargo test abs_native",
                        "rc": 0,
                        "required": False,
                        "skipped": True,
                    }
                )
        else:
            step(
                "cargo test abs_native",
                [py, "scripts/cargo_test_abs_native.py"],
                timeout=900,
                required=True,
            )
            if args.hard:
                step(
                    "cargo test rust_bridge",
                    [
                        cargo,
                        "test",
                        "--manifest-path",
                        str(ROOT / "bridge" / "rust_bridge" / "Cargo.toml"),
                    ],
                    timeout=600,
                    required=True,
                )

    step("secrets scan", [py, "scripts/check_secrets.py"])

    if not args.skip_gate:
        step("prod_gate", [py, "scripts/prod_gate.py"])
        step("k8s_prod_gate", [py, "scripts/k8s_prod_gate.py"])
        step("verify_prod_stack", [py, "scripts/verify_prod_stack.py"])
        step(
            "industrial_gate",
            [py, "scripts/industrial_gate.py"],
            timeout=180,
        )

    if args.hard:
        step(
            "industrial waves needles",
            [
                py,
                "scripts/verify_industrial_waves.py",
                "--skip-gate",
                "--skip-pytest",
            ],
            timeout=180,
        )
        step(
            "experimental R&D (units + labs)",
            [py, "scripts/verify_experimental_rd.py", "-q"],
            timeout=1800,
        )

    if not args.skip_pytest:
        if args.quick_pytest:
            cmd = [py, "-m", "pytest", "-q", "--tb=line", *QUICK_PYTEST]
            label = "pytest industrial slice"
        else:
            cmd = [py, "-m", "pytest", "-q", "--tb=line", "tests/"]
            label = "pytest tests/ (full tree)"
        step(label, cmd, timeout=int(args.pytest_timeout))

    _banner("soak honesty (read-only; soak NOT started)")
    cb = _load_check_blockchain()
    soak = cb.soak_honesty()
    cb._print_soak(soak["experimental_48h"], "48h Experimental")
    cb._print_soak(soak["strict_5h"], "5h STRICT")
    print(f"  {soak['note']}")
    soak_rc = 0
    if args.require_soak_48h and not soak["claim_48h_pass"]:
        soak_rc = 1
        errors.append("48h Experimental soak is not PASS")
    steps.append(
        {
            "name": "soak_honesty",
            "rc": soak_rc,
            "required": bool(args.require_soak_48h),
            "claim_48h_pass": soak["claim_48h_pass"],
        }
    )

    if not args.skip_live:
        _bind_prod_smoke_wallet()
        rc = step(
            "live mesh probe (deep)",
            [py, "scripts/verify_prod_mesh_probe.py"],
            timeout=120,
        )
        if rc != 0:
            mesh_down = True
        step(
            "consistency harness (3 nodes)",
            [py, "scripts/check_harness_probe.py"],
            timeout=90,
        )
        step(
            "mesh catch-up / wire probe",
            [py, "scripts/check_mesh_catchup.py"],
            timeout=60,
        )
        step(
            "GET /status SLO",
            None,
            runner=_status_slo,
        )
        step(
            "soak preflight (does not start soak)",
            [py, "scripts/soak_preflight.py"],
            timeout=90,
        )
        step(
            "verify_p2p_ci prod-mesh3-live",
            [
                py,
                "scripts/verify_p2p_ci.py",
                "--mode",
                "prod-mesh3-live",
                "--url1",
                "http://127.0.0.1:18180",
                "--url2",
                "http://127.0.0.1:18181",
                "--url3",
                "http://127.0.0.1:18182",
                "--wait",
                str(int(args.p2p_wait)),
            ],
            timeout=int(args.p2p_wait) + 60,
        )
        docker = shutil.which("docker")
        if docker is None:
            if args.hard or args.require_baked_root:
                errors.append("docker not on PATH (baked state_root required)")
                print("FAIL: docker not on PATH — baked state_root required")
                steps.append(
                    {
                        "name": "baked committed state_root (running image)",
                        "rc": 127,
                        "required": True,
                    }
                )
            else:
                warnings.append("docker not on PATH; skipped baked state-root")
                print("WARN: docker not on PATH — skip baked state-root")
        else:
            step(
                "baked committed state_root (running image)",
                [
                    docker,
                    "exec",
                    CONTAINER,
                    "python",
                    "scripts/check_baked_state_root.py",
                ],
                timeout=60,
                required=bool(args.require_baked_root or args.hard),
            )

    ok = not errors
    elapsed = round(time.time() - started, 2)
    report = {
        "script": "verify_full_blockchain.py",
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "elapsed_sec": elapsed,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "soak": soak,
        "honesty": [
            "PASS is not public mainnet",
            "this script does not start soak",
            "this script does not rebuild Docker",
            "live mesh Python may be older than host until the next bake",
            "Experimental 48h TCP+TLS soak PASS is packaged at docs/evidence/runs/0a7932c4/",
            "that PASS is not libp2p cutover, not Long-Range, not public mainnet",
            "--hard does not require a 48h soak PASS (read-only honesty only)",
            "ADR 0019 rust-libp2p hard gate is a separate command (needs Cargo feature libp2p)",
        ],
        "hard": bool(args.hard),
        "run": [
            ".\\scripts\\verify_hard_all.ps1",
            "python scripts/verify_full_blockchain.py --hard",
            ".\\scripts\\verify_full_blockchain.ps1",
            "python scripts/verify_full_blockchain.py",
            "python scripts/verify_full_blockchain.py --skip-live",
            "python scripts/verify_full_blockchain.py --quick-pytest",
        ],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    _banner("SCOREBOARD")
    for rec in steps:
        flag = "OK  " if rec.get("rc") == 0 else ("SKIP" if rec.get("skipped") else "FAIL")
        req = "req" if rec.get("required", True) else "opt"
        print(f"  {flag}  [{req}]  {rec.get('name')}")
    print()
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"  - {w}")
    if ok:
        soak_word = "SOAK_48H_PASS" if soak["claim_48h_pass"] else "SOAK_48H_NOT_PASS"
        print(f"RESULT: OK  {soak_word}")
        print(f"Report: {REPORT_PATH}")
        print(" Honesty: not public mainnet. Soak was not started.")
        return 0
    print("RESULT: FAIL")
    for err in errors:
        print(f"  - {err}")
    print(f"Report: {REPORT_PATH}")
    live_only = bool(errors) and all(
        ("mesh" in e.lower() or "harness" in e.lower() or "catch-up" in e.lower()
         or "status SLO" in e or "p2p_ci" in e.lower() or "preflight" in e.lower())
        for e in errors
    )
    if (not args.hard) and mesh_down and live_only:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
