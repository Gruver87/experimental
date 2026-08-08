#!/usr/bin/env python3
"""Package ADR 0019 rust-libp2p lab evidence (experimental only).

Runs selected labs, writes stdout + manifest under docs/evidence/runs/libp2p-rd.
Does not claim tip proof or prod mesh libp2p.

Usage:
  python scripts/package_libp2p_evidence.py
  python scripts/package_libp2p_evidence.py --skip-run  # pack existing logs only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
OUT_DEFAULT = ROOT / "docs" / "evidence" / "runs" / "libp2p-rd"

LABS = (
    "scripts/libp2p_rust_two_node_lab.py",
    "scripts/libp2p_rust_wire_lab.py",
    "scripts/libp2p_rust_three_node_lab.py",
    "scripts/libp2p_rust_soak_lab.py",
    "scripts/libp2p_mixed_dual_stack_lab.py",
    "scripts/libp2p_rust_gossip_lab.py",
    "scripts/libp2p_rust_identity_mdns_lab.py",
    "scripts/libp2p_rust_kad_lab.py",
    "scripts/libp2p_rust_abs_announce_lab.py",
    "scripts/libp2p_rust_relay_limits_lab.py",
    "scripts/libp2p_rust_blocklist_lab.py",
    "scripts/libp2p_rust_status_surface_lab.py",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
        ).strip()
    except Exception:
        return "unknown"


def _run_lab(rel: str, out_dir: Path) -> Dict[str, Any]:
    name = Path(rel).stem + ".log"
    dest = out_dir / name
    proc = subprocess.run(
        [sys.executable, str(ROOT / rel)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    body = (proc.stdout or "") + (proc.stderr or "")
    dest.write_text(body, encoding="utf-8")
    ok = proc.returncode == 0 and "PASS" in (proc.stdout or "")
    return {
        "lab": rel,
        "status": "pass" if ok else "fail",
        "exit_code": int(proc.returncode),
        "log": str(dest.relative_to(ROOT)),
        "sha256": _sha256(dest.read_bytes()),
        "bytes": dest.stat().st_size,
    }


def package(*, out_dir: Path, skip_run: bool) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: List[Dict[str, Any]] = []
    if skip_run:
        for rel in LABS:
            log = out_dir / (Path(rel).stem + ".log")
            if log.is_file():
                results.append(
                    {
                        "lab": rel,
                        "status": "present",
                        "log": str(log.relative_to(ROOT)),
                        "sha256": _sha256(log.read_bytes()),
                        "bytes": log.stat().st_size,
                    }
                )
            else:
                results.append({"lab": rel, "status": "missing"})
    else:
        for rel in LABS:
            try:
                results.append(_run_lab(rel, out_dir))
            except Exception as exc:
                results.append({"lab": rel, "status": "error", "error": str(exc)})

    manifest: Dict[str, Any] = {
        "schema": "abs.libp2p_rd_evidence.v1",
        "created_unix": int(time.time()),
        "commit": _git_commit(),
        "honesty": [
            "experimental_only",
            "not_prod_mesh_libp2p",
            "not_tip_proof",
            "FEATURE_LIBP2P_opt_in",
        ],
        "labs": results,
        "summary": {
            "pass": sum(1 for r in results if r.get("status") == "pass"),
            "fail": sum(1 for r in results if r.get("status") == "fail"),
            "missing": sum(1 for r in results if r.get("status") == "missing"),
            "error": sum(1 for r in results if r.get("status") == "error"),
        },
    }
    man_path = out_dir / "manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"OK: wrote {man_path.relative_to(ROOT)}")
    print(f"  summary: {manifest['summary']}")
    print(f"  honesty: {', '.join(manifest['honesty'])}")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--skip-run", action="store_true")
    args = ap.parse_args()
    man = package(out_dir=args.out, skip_run=bool(args.skip_run))
    fails = int(man["summary"].get("fail", 0)) + int(man["summary"].get("error", 0))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
