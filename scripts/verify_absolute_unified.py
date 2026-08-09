#!/usr/bin/env python3
"""Unified Absolute Blockchain operator verify (Hybrid + Experimental).

Treats the audit-frozen Hybrid mesh and Experimental R&D as one operator view
of the same blockchain project — without merging the repos or claiming that
rust-libp2p is the industrial production mesh.

Stages (fail-closed unless --keep-going):
  1) Hybrid       — scripts/verify_project.py  (TCP+TLS industrial path)
  2) Experimental — scripts/verify_experimental_rd.py  (Profile F units/labs)
  3) ADR 0019     — scripts/verify_adr0019_libp2p_hard.py  (opt-in rust-libp2p)

Usage (from Experimental root, or any cwd with paths set):
  python scripts/verify_absolute_unified.py
  python scripts/verify_absolute_unified.py --mode standard
  python scripts/verify_absolute_unified.py --mode full
  python scripts/verify_absolute_unified.py --hybrid-root ..\\Absolute_Blockchain_Ultimate_Hybrid
  python scripts/verify_absolute_unified.py --skip-libp2p
  powershell -ExecutionPolicy Bypass -File scripts\\verify_absolute_unified.ps1

Modes:
  quick    — Hybrid quick + Experimental RD (no ADR 0019 hard; ~minutes)
  standard — Hybrid standard + Experimental RD + ADR 0019 hard
  full     — Hybrid industrial + Experimental RD + ADR 0019 hard

Honesty:
  PASS here != public mainnet / tip existence proof / firm audit complete.
  Experimental libp2p PASS != prod mesh cutover (TCP+TLS remains default).
  Hybrid audit freeze is preserved — this script only verifies, never merges.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EXPERIMENTAL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HYBRID = EXPERIMENTAL_ROOT.parent / "Absolute_Blockchain_Ultimate_Hybrid"


def _safe_print(text: str) -> None:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.buffer.write((text + "\n").encode(enc, errors="replace"))
    sys.stdout.flush()


def _banner(text: str) -> None:
    _safe_print("")
    _safe_print("=" * 72)
    _safe_print(f" {text}")
    _safe_print("=" * 72)


def _run_stage(
    *,
    name: str,
    cwd: Path,
    cmd: list[str],
    keep_going: bool,
    steps: list[dict],
) -> bool:
    _safe_print("")
    _safe_print(f">>> [{name}]")
    _safe_print(f"    cwd: {cwd}")
    _safe_print(f"    $ {' '.join(cmd)}")
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd))
        rc = int(proc.returncode)
    except OSError as exc:
        rc = 127
        _safe_print(f"FAIL: spawn error: {exc}")
    elapsed = round(time.perf_counter() - t0, 1)
    ok = rc == 0
    steps.append(
        {
            "name": name,
            "cwd": str(cwd),
            "cmd": cmd,
            "ok": ok,
            "exit": rc,
            "elapsed_sec": elapsed,
        }
    )
    status = "PASS" if ok else "FAIL"
    _safe_print(f"[{status}] {name}  ({elapsed}s, exit={rc})")
    if not ok and not keep_going:
        raise SystemExit(f"STAGE FAIL: {name} (exit {rc})")
    return ok


def _resolve_hybrid(path: str | None) -> Path:
    raw = (path or os.environ.get("ABS_HYBRID_ROOT") or str(DEFAULT_HYBRID)).strip()
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"FAIL: Hybrid root not found: {root}")
    marker = root / "scripts" / "verify_project.py"
    if not marker.is_file():
        raise SystemExit(f"FAIL: not a Hybrid repo (missing {marker})")
    return root


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--mode",
        choices=("quick", "standard", "full"),
        default="standard",
        help="quick=hybrid quick+RD; standard=+ADR0019 hard; full=hybrid industrial+all",
    )
    ap.add_argument(
        "--hybrid-root",
        default=None,
        help="Path to Absolute_Blockchain_Ultimate_Hybrid (or ABS_HYBRID_ROOT)",
    )
    ap.add_argument(
        "--experimental-root",
        default=None,
        help="Path to Absolute_Blockchain_Experimental (default: this repo)",
    )
    ap.add_argument("--min-soak-hours", type=float, default=48.0)
    ap.add_argument("--skip-hybrid", action="store_true")
    ap.add_argument("--skip-experimental-rd", action="store_true")
    ap.add_argument("--skip-libp2p", action="store_true", help="skip ADR 0019 hard")
    ap.add_argument("--rebuild-libp2p", action="store_true", help="maturin rebuild wheel")
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    experimental = Path(args.experimental_root).resolve() if args.experimental_root else EXPERIMENTAL_ROOT
    if not (experimental / "scripts" / "verify_adr0019_libp2p_hard.py").is_file():
        raise SystemExit(f"FAIL: Experimental root missing ADR hard script: {experimental}")

    hybrid = None if args.skip_hybrid else _resolve_hybrid(args.hybrid_root)
    py = sys.executable
    started = time.time()
    steps: list[dict] = []
    report: dict = {
        "script": "verify_absolute_unified.py",
        "mode": args.mode,
        "hybrid_root": str(hybrid) if hybrid else None,
        "experimental_root": str(experimental),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "ok": False,
        "honesty": [
            "Two repos, one operator view — not a git merge / not a single deployable tree",
            "PASS is not public mainnet / tip existence proof / firm audit PDF",
            "Hybrid TCP+TLS remains the industrial default mesh",
            "Experimental rust-libp2p PASS does not authorize prod libp2p cutover",
            "feature_libp2p must stay false on prod mesh JSON",
            "Hybrid audit freeze preserved — verify only, never push R&D into Hybrid",
        ],
    }

    _banner(f"ABSOLUTE UNIFIED VERIFY  mode={args.mode}")
    _safe_print(f"Hybrid:       {hybrid or '(skipped)'}")
    _safe_print(f"Experimental: {experimental}")
    _safe_print(f"Python:       {py}")
    _safe_print("Honesty: green != one merged prod tree / != public mainnet")

    all_ok = True
    try:
        if hybrid is not None:
            hybrid_mode = {
                "quick": "quick",
                "standard": "standard",
                "full": "industrial",
            }[args.mode]
            cmd = [py, "scripts/verify_project.py", "--mode", hybrid_mode]
            if args.mode == "full":
                cmd += ["--min-soak-hours", str(args.min_soak_hours)]
            ok = _run_stage(
                name=f"hybrid:verify_project:{hybrid_mode}",
                cwd=hybrid,
                cmd=cmd,
                keep_going=args.keep_going,
                steps=steps,
            )
            all_ok = all_ok and ok

        if not args.skip_experimental_rd:
            rd_cmd = [py, "scripts/verify_experimental_rd.py"]
            if args.quiet:
                rd_cmd.append("-q")
            ok = _run_stage(
                name="experimental:verify_experimental_rd",
                cwd=experimental,
                cmd=rd_cmd,
                keep_going=args.keep_going,
                steps=steps,
            )
            all_ok = all_ok and ok

        run_libp2p = (not args.skip_libp2p) and (args.mode in ("standard", "full"))
        if args.mode == "quick" and not args.skip_libp2p:
            _safe_print("")
            _safe_print("NOTE: mode=quick skips ADR 0019 hard (use --mode standard|full)")
        if run_libp2p:
            hard_cmd = [py, "scripts/verify_adr0019_libp2p_hard.py"]
            if args.rebuild_libp2p:
                hard_cmd.append("--rebuild")
            if args.keep_going:
                hard_cmd.append("--keep-going")
            if args.quiet:
                hard_cmd.append("-q")
            ok = _run_stage(
                name="experimental:adr0019_libp2p_hard",
                cwd=experimental,
                cmd=hard_cmd,
                keep_going=args.keep_going,
                steps=steps,
            )
            all_ok = all_ok and ok

        report["ok"] = all_ok
        if not all_ok:
            raise SystemExit("UNIFIED FAIL: one or more stages failed (--keep-going)")
    except SystemExit as exc:
        report["error"] = str(exc)
        if not args.keep_going:
            all_ok = False
            report["ok"] = False
        _safe_print(f"\nFAIL: {exc}")

    report["ended_utc"] = datetime.now(timezone.utc).isoformat()
    report["elapsed_sec"] = round(time.time() - started, 1)
    report["ok"] = bool(report.get("ok")) and all_ok

    out_dir = experimental / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "verify_absolute_unified.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    _banner(
        ("PASS" if report["ok"] else "FAIL")
        + f" - unified mode={args.mode} - {report['elapsed_sec']}s"
    )
    _safe_print(
        "Stages: "
        + ", ".join(
            f"{s['name']}={'OK' if s['ok'] else 'FAIL'}" for s in steps
        )
    )
    _safe_print(f"Report: {out_path}")
    _safe_print("Honesty:")
    for line in report["honesty"]:
        _safe_print(f"  - {line}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
