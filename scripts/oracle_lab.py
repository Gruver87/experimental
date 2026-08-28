#!/usr/bin/env python3
"""Oracle feed lab (Profile aux — ADR 0016 sprout, lab-only).

Exercises signed HMAC submit + persist + reject bad sig without live mesh.
Oracle feeds live in SQLite aux — not prod L1 trust path on 778888.

Usage:
  python scripts/oracle_lab.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridge.oracle_auth import sign_payload
from features.oracle_registry import OracleFeedRegistry
from storage.database import Database


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    secret = "oracle-lab-hmac-secret"
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "oracle_lab.db"))
        db.initialize()
        reg = OracleFeedRegistry(db, secret=secret)

        # Internal ingest (dev path)
        feed_id = reg.ingest_internal("bitcoin", 65000.5, "coingecko")
        if not feed_id:
            return _fail("ingest_internal must return feed_id")
        rows = reg.list_feeds(symbol="bitcoin", limit=5)
        if len(rows) != 1 or rows[0]["value"] != 65000.5:
            return _fail("persisted feed mismatch")

        # Bad HMAC must refuse
        bad = reg.submit_feed("ethereum", 3200.0, signature="bad-sig")
        if bad.get("ok") is not False:
            return _fail("bad signature must refuse")
        if "invalid" not in str(bad.get("error", "")).lower():
            return _fail("expected invalid signature error")

        # Signed submit
        payload = {
            "symbol": "solana",
            "value": 145.25,
            "source": "reporter",
            "reporter": "0x" + "a" * 40,
            "ts": 1718123456,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        sig = sign_payload(secret, raw)
        ok = reg.submit_feed(
            symbol="solana",
            value=145.25,
            source="reporter",
            reporter=payload["reporter"],
            signature=sig,
            payload=payload,
        )
        if ok.get("ok") is not True:
            return _fail(f"signed submit failed: {ok}")
        latest = reg.latest_by_symbol("solana")
        if latest is None or latest["value"] != 145.25:
            return _fail("latest_by_symbol after signed submit")

        # Missing secret must refuse signed path
        reg_no_secret = OracleFeedRegistry(db, secret="")
        nosig = reg_no_secret.submit_feed("btc", 1.0, signature="x", require_signature=True)
        if nosig.get("ok") is not False:
            return _fail("missing secret must refuse signed submit")

        db.close()

    print("OK: oracle_lab PASS (HMAC submit + persist; aux DB only; not prod 778888)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
