#!/usr/bin/env python3
"""Oracle feed lab (Profile aux — ADR 0016 sprout, lab-only).

Wave-1: HMAC submit + persist + refuse bad/missing secret.
Wave-2: quorum median + one-vote-per-reporter dedupe (no live mesh).

Oracle feeds live in SQLite aux — not prod L1 trust path on 778888.

Usage:
  python scripts/oracle_lab.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
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

        # Wave-2: quorum median (unsigned reports when secret="")
        quorum_reg = OracleFeedRegistry(db, secret="")
        now = int(time.time())
        for reporter, value in (("rep1", 100.0), ("rep2", 102.0), ("rep3", 101.0)):
            out = quorum_reg.submit_report(
                "btc",
                value,
                reporter,
                payload={
                    "symbol": "btc",
                    "value": float(value),
                    "reporter": reporter,
                    "ts": now,
                },
            )
            if out.get("ok") is not True:
                return _fail(f"submit_report {reporter}: {out}")

        # Same reporter twice — only latest vote counts (still 3 unique; keep tight band)
        dup = quorum_reg.submit_report(
            "btc",
            100.5,
            "rep1",
            payload={
                "symbol": "btc",
                "value": 100.5,
                "reporter": "rep1",
                "ts": now + 1,
            },
        )
        if dup.get("ok") is not True:
            return _fail(f"dedupe resubmit: {dup}")

        agg = quorum_reg.aggregate_symbol("btc", quorum=2, max_age_sec=3600)
        if agg is None:
            return _fail("aggregate_symbol must reach quorum")
        if int(agg.get("unique_reporters") or 0) != 3:
            return _fail(f"expected 3 unique reporters, got {agg}")
        # Latest: rep1=100.5, rep2=102, rep3=101 → sorted [100.5, 101, 102], median=101
        if float(agg["value"]) != 101.0:
            return _fail(f"median after dedupe expected 101.0, got {agg['value']}")

        # Below quorum must return None
        alone = OracleFeedRegistry(db, secret="")
        alone.submit_report(
            "eth",
            1.0,
            "only-one",
            payload={"symbol": "eth", "value": 1.0, "reporter": "only-one", "ts": now},
        )
        if alone.aggregate_symbol("eth", quorum=2, max_age_sec=3600) is not None:
            return _fail("below quorum must not aggregate")

        db.close()

    print("OK: oracle_lab PASS (HMAC + quorum median + reporter dedupe; not prod 778888)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
