#!/usr/bin/env python3
"""Package ADR 0019 rust-libp2p lab evidence (experimental only).

Lab list is the same tuple as ``verify_adr0019_libp2p_hard.py`` (fail-closed:
the pack cannot silently stop at an old slice). Runs those labs and writes
stdout + manifest under docs/evidence/runs/libp2p-rd.

Does not claim tip proof or prod mesh libp2p.

Usage:
  python scripts/package_libp2p_evidence.py
  python scripts/package_libp2p_evidence.py --skip-run  # pack existing logs only
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
OUT_DEFAULT = ROOT / "docs" / "evidence" / "runs" / "libp2p-rd"
_HARD = ROOT / "scripts" / "verify_adr0019_libp2p_hard.py"


def hard_verify_lab_paths() -> Tuple[str, ...]:
    """Return hard-verify lab relative paths. Missing/empty list is an error."""
    spec = importlib.util.spec_from_file_location("verify_adr0019_libp2p_hard", _HARD)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_HARD}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    raw = getattr(mod, "LABS", None)
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("verify_adr0019_libp2p_hard.LABS missing or empty")
    out: list[str] = []
    for item in raw:
        if not (isinstance(item, tuple) and len(item) == 2):
            raise RuntimeError(f"bad LABS entry: {item!r}")
        rel = str(item[1])
        if not (ROOT / rel).is_file():
            raise RuntimeError(f"hard-verify lab missing on disk: {rel}")
        out.append(rel)
    if "scripts/libp2p_rust_external_addrs_persist_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice BP persist lab")
    if "scripts/libp2p_rust_external_addrs_atomic_persist_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice BQ atomic persist lab")
    if "scripts/libp2p_rust_external_addrs_max_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice BR advertised-max lab")
    if "scripts/libp2p_rust_listen_derived_external_max_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice BS listen-derived-max lab")
    if "scripts/libp2p_rust_advertised_externals_shared_max_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice BT shared-max lab")
    if "scripts/libp2p_rust_advertised_externals_all_paths_max_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice BU all-paths-max lab")
    if "scripts/libp2p_rust_identify_listen_addrs_capped_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice BV identify-listen-cap lab")
    if "scripts/libp2p_rust_mdns_listen_addrs_capped_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice BW mdns-listen-cap lab")
    if "scripts/libp2p_rust_kad_listen_addrs_capped_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice BX kad-listen-cap lab")
    if "scripts/libp2p_rust_autonat_listen_addrs_capped_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice BY autonat-listen-cap lab")
    if "scripts/libp2p_rust_upnp_listen_addrs_capped_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice BZ upnp-listen-cap lab")
    if "scripts/libp2p_rust_advertised_externals_libp2p_book_max_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice CA libp2p-book-max lab")
    if "scripts/libp2p_rust_dcutr_candidates_capped_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice CB dcutr-candidates-cap lab")
    if "scripts/libp2p_rust_identify_candidates_capped_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice CC identify-candidates-cap lab")
    if "scripts/libp2p_rust_external_addrs_replace_no_unlink_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice CD persist-replace-no-unlink lab")
    if "scripts/libp2p_rust_bootstrap_peerstore_atomic_persist_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice CE bootstrap-peerstore-atomic lab")
    if "scripts/libp2p_rust_identity_atomic_persist_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice CF identity-atomic lab")
    if "scripts/libp2p_rust_persist_parent_dir_fsync_lab.py" not in out:
        raise RuntimeError("hard-verify LABS missing Slice CG parent-dir-fsync lab")
    return tuple(out)


LABS = hard_verify_lab_paths()


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
            "listed": len(LABS),
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
