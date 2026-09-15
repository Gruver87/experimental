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


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE from .env into os.environ if not already set (no logging of values)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv(ROOT / ".env")

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
    base = http.rstrip("/")

    def _apply_ms(ms: object) -> None:
        if not isinstance(ms, dict):
            return
        if ms.get("store_demoted") is not None:
            out["demoted"] = ms.get("store_demoted", ms.get("demoted"))
        elif ms.get("demoted") is not None:
            out["demoted"] = ms.get("demoted")
        backend = ms.get("store_backend", ms.get("backend"))
        if backend:
            out["store_backend"] = backend

    # Prefer slim probe under load; fall back to full /status then /health/ready.
    for path in ("/status?probe=1", "/status", "/health/ready"):
        try:
            st = _api(f"{base}{path}", timeout=12)
            if not isinstance(st, dict):
                continue
            if st.get("mempool_size") is not None:
                out["mempool_size"] = st.get("mempool_size")
            _apply_ms(st.get("mempool_store") or {})
            if out["demoted"] is not None and out["store_backend"]:
                break
        except Exception:
            continue
    return out


def _is_timeout(exc: BaseException) -> bool:
    """Classify load HOL / socket stalls as soft (not refuse_fail)."""
    if isinstance(exc, TimeoutError):
        return True
    try:
        import socket

        if isinstance(exc, socket.timeout):
            return True
    except Exception:
        pass
    # urllib wraps timeouts as URLError(reason=...) on Windows.
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException) and _is_timeout(reason):
        return True
    msg = f"{type(exc).__name__} {exc} {reason}".lower()
    return (
        "timed out" in msg
        or "timeout" in msg
        or "winerror 10060" in msg
    )


def _refuse_empty_tx(http: str, *, timeout: float = 45.0) -> tuple[str, str]:
    """POST bad /tx/send. Returns (ok|soft|fail, detail)."""
    try:
        resp = _post_json(
            http.rstrip("/"),
            "/tx/send",
            {
                "from": "0x" + "0" * 40,
                "to": "0x" + "1" * 40,
                "amount": 0.01,
                "fee": 0.0,
                "nonce": 0,
            },
            timeout=timeout,
        )
        if isinstance(resp, dict) and (
            resp.get("success") is False
            or resp.get("error")
            or resp.get("refused")
            or resp.get("valid") is False
        ):
            return "ok", f"refused_body={list(resp.keys())[:6]}"
        return "fail", f"unexpected_accept={resp!r}"[:200]
    except urllib.error.HTTPError as exc:
        if 400 <= int(exc.code) < 600:
            return "ok", f"http_{exc.code}"
        return "fail", f"http_{exc.code}"
    except Exception as exc:
        if _is_timeout(exc):
            return "soft", f"timeout:{exc}"
        return "fail", f"error:{exc}"


def _admit_smoke(http: str, wallet: str) -> tuple[str, str]:
    """Signed deploy smoke. Returns (ok|soft|fail, detail)."""
    try:
        from prod_evm_smoke import _deploy_via_mempool, _ensure_deployer_balance, _wallet_address

        deployer = _wallet_address(wallet)
        _ensure_deployer_balance(http, deployer, min_balance=1.0)
        tx_hash, contract, height = _deploy_via_mempool(http, wallet)
        return "ok", f"deploy tx={tx_hash[:16]}... h={height} c={contract[:14]}..."
    except Exception as exc:
        if _is_timeout(exc):
            return "soft", f"timeout:{exc}"
        return "fail", f"admit_fail:{exc}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Mempool validation soak sidecar")
    ap.add_argument("--http", default="http://127.0.0.1:18180")
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--interval-sec", type=int, default=300)
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
    admit_ok = admit_soft = admit_fail = 0
    refuse_ok = refuse_soft = refuse_fail = 0
    backoff = float(args.interval_sec)

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
            kind, detail = _refuse_empty_tx(args.http)
            if kind == "ok":
                refuse_ok += 1
                _log(log, f"OK refuse {detail}")
                backoff = float(args.interval_sec)
            elif kind == "soft":
                refuse_soft += 1
                _log(log, f"WARN refuse {detail}")
                backoff = min(backoff * 1.5, 900.0)
            else:
                refuse_fail += 1
                _log(log, f"FAIL refuse expected {detail}")

        if not args.skip_admit:
            kind, detail = _admit_smoke(args.http, args.wallet)
            if kind == "ok":
                admit_ok += 1
                _log(log, f"OK admit {detail}")
                backoff = float(args.interval_sec)
            elif kind == "soft":
                admit_soft += 1
                _log(log, f"WARN admit {detail}")
                backoff = min(backoff * 1.5, 900.0)
            else:
                admit_fail += 1
                _log(log, f"FAIL admit {detail}")

        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(backoff, remaining))

    report = {
        "kind": "mempool_validation_sidecar",
        "honesty": ["NOT 48h soak claim", "NOT mainnet", "NOT Hybrid pin"],
        "cycles": cycle,
        "admit_ok": admit_ok,
        "admit_soft": admit_soft,
        "admit_fail": admit_fail,
        "refuse_ok": refuse_ok,
        "refuse_soft": refuse_soft,
        "refuse_fail": refuse_fail,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        # Timeouts under mesh load are soft; unexpected accept / hard errors fail.
        "passed": refuse_fail == 0 and admit_fail == 0 and cycle > 0,
    }
    out = ROOT / "logs" / "mempool_validation_sidecar_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _log(log, f"sidecar done passed={report['passed']} report={out}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
