#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In-window mempool+validation sidecar for prod mesh soak (Experimental).

Periodically:
  1) signed mempool deploy smoke (admit path)
  2) known-bad admits that must refuse (empty / low fee)

Does NOT start soak. Intended as a companion to soak_monitor / STRICT mesh.
Honesty: not 48h evidence by itself; not mainnet; not Hybrid pin.

Usage (repo root, mesh up on :18180):
  python scripts/mempool_validation_sidecar.py --hours 2 --interval-sec 120
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from verify_p2p_ci import _api, _post_json  # noqa: E402


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(path: Path, msg: str) -> None:
    line = f"{_ts()} {msg}"
    print(line, flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _metrics_snippet(http: str) -> dict:
    out = {
        "mempool_size": None,
        "demoted": None,
        "store_backend": None,
    }
    try:
        st = _api(f"{http.rstrip('/')}/status")
        out["mempool_size"] = st.get("mempool_size")
        ms = st.get("mempool_store") or {}
        if isinstance(ms, dict):
            out["demoted"] = ms.get("demoted")
            out["store_backend"] = ms.get("backend")
    except Exception:
        pass
    return out


def _refuse_empty_tx(http: str) -> tuple[bool, str]:
    """POST a structurally empty /tx/send — expect refuse (4xx/5xx or success:false)."""
    try:
        resp = _post_json(
            f"{http.rstrip('/')}/tx/send",
            {
                "from": "0x" + "0" * 40,
                "to": "0x" + "1" * 40,
                "amount": 0.01,
                "fee": 0.0,
                "nonce": 0,
            },
            timeout=10,
        )
        if isinstance(resp, dict) and (
            resp.get("success") is False
            or resp.get("error")
            or resp.get("refused")
            or resp.get("valid") is False
        ):
            return True, f"refused_body={list(resp.keys())[:6]}"
        return False, f"unexpected_accept={resp!r}"[:200]
    except urllib.error.HTTPError as exc:
        # 4xx/5xx = refuse at boundary — PASS for this probe.
        if 400 <= int(exc.code) < 600:
            return True, f"http_{exc.code}"
        return False, f"http_{exc.code}"
    except Exception as exc:
        return False, f"error:{exc}"


def _admit_smoke(http: str, wallet: str) -> tuple[bool, str]:
    try:
        from prod_evm_smoke import _deploy_via_mempool, _ensure_deployer_balance, _wallet_address

        deployer = _wallet_address(wallet)
        _ensure_deployer_balance(http, deployer, min_balance=1.0)
        tx_hash, contract, height = _deploy_via_mempool(http, wallet)
        return True, f"deploy tx={tx_hash[:16]}… h={height} c={contract[:14]}…"
    except Exception as exc:
        return False, f"admit_fail:{exc}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Mempool validation soak sidecar")
    ap.add_argument("--http", default="http://127.0.0.1:18180")
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--interval-sec", type=int, default=120)
    ap.add_argument(
        "--wallet",
        default=str(ROOT / "data" / "prod_mesh" / "wallets" / "validator-1.wallet.json"),
    )
    ap.add_argument(
        "--log-file",
        default=str(ROOT / "logs" / "mempool_validation_sidecar.log"),
    )
    ap.add_argument("--skip-admit", action="store_true")
    ap.add_argument("--skip-refuse", action="store_true")
    args = ap.parse_args()

    log = Path(args.log_file)
    deadline = time.time() + max(0.1, float(args.hours)) * 3600.0
    cycle = 0
    admit_ok = admit_fail = refuse_ok = refuse_fail = 0

    _log(
        log,
        "sidecar start "
        f"http={args.http} hours={args.hours} interval={args.interval_sec}s "
        "NOT 48h / NOT mainnet / NOT Hybrid",
    )

    while time.time() < deadline:
        cycle += 1
        snap = _metrics_snippet(args.http)
        _log(
            log,
            f"cycle={cycle} status mempool_size={snap.get('mempool_size')} "
            f"store={snap.get('store_backend')} demoted={snap.get('demoted')}",
        )
        if snap.get("demoted") in (True, 1, "1", "true"):
            _log(log, "FAIL mempool_store demoted under sidecar — abort")
            return 2

        if not args.skip_refuse:
            ok, detail = _refuse_empty_tx(args.http)
            if ok:
                refuse_ok += 1
                _log(log, f"OK refuse {detail}")
            else:
                refuse_fail += 1
                _log(log, f"FAIL refuse expected {detail}")

        if not args.skip_admit:
            ok, detail = _admit_smoke(args.http, args.wallet)
            if ok:
                admit_ok += 1
                _log(log, f"OK admit {detail}")
            else:
                admit_fail += 1
                _log(log, f"WARN admit {detail}")

        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(float(args.interval_sec), remaining))

    report = {
        "kind": "mempool_validation_sidecar",
        "honesty": ["NOT 48h soak claim", "NOT mainnet", "NOT Hybrid pin"],
        "cycles": cycle,
        "admit_ok": admit_ok,
        "admit_fail": admit_fail,
        "refuse_ok": refuse_ok,
        "refuse_fail": refuse_fail,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "passed": refuse_fail == 0 and admit_fail == 0 and cycle > 0,
    }
    out = ROOT / "logs" / "mempool_validation_sidecar_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _log(log, f"sidecar done passed={report['passed']} report={out}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
