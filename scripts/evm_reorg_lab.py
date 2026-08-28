#!/usr/bin/env python3
"""EVM reorg index honesty lab (Profile A wave-11).

SQLite: persist evm_logs at height 2, truncate above 1, assert logs purged.
No live mesh. Mirrors tests/unit/test_sqlite_reorg_parity.py.

Usage:
  python scripts/evm_reorg_lab.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.database import Database


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    Path(path).unlink(missing_ok=True)
    db = Database(path)
    db.initialize()
    try:
        if not db.save_block(
            {
                "number": 1,
                "height": 1,
                "hash": "aa" * 32,
                "previous_hash": "00" * 32,
                "parent_hash": "00" * 32,
                "timestamp": 1,
                "transactions": [],
                "state_root": "11" * 32,
            }
        ):
            return _fail("save_block height 1")
        if not db.save_block(
            {
                "number": 2,
                "height": 2,
                "hash": "bb" * 32,
                "previous_hash": "aa" * 32,
                "parent_hash": "aa" * 32,
                "timestamp": 2,
                "transactions": [],
                "state_root": "22" * 32,
            }
        ):
            return _fail("save_block height 2")
        saved = db.save_evm_logs(
            "0xabc",
            [{"topics": [], "data": "0x", "log_index": 0}],
            block_height=2,
            tx_hash="cc" * 32,
        )
        if saved < 1:
            return _fail("save_evm_logs")
        db.record_tx_propagation_event(
            "cc" * 32,
            "mined",
            peer_id="p1",
            block_height=2,
        )
        with db.atomic():
            db.reorg_truncate_above(1)
        if db.get_chain_tip() != 1:
            return _fail("tip after reorg must be 1")
        n_logs = db.conn.execute("SELECT COUNT(*) AS c FROM evm_logs").fetchone()["c"]
        if n_logs != 0:
            return _fail("evm_logs must be purged above height 1")
        n_prop = db.conn.execute(
            "SELECT COUNT(*) AS c FROM tx_propagation_events WHERE block_height > 1"
        ).fetchone()["c"]
        if n_prop != 0:
            return _fail("tx_propagation above 1 must be purged")
    finally:
        db.close()
        Path(path).unlink(missing_ok=True)

    print("OK: evm_reorg_lab PASS (SQLite reorg purges evm_logs; not mesh soak)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
