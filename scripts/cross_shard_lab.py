#!/usr/bin/env python3
"""Cross-shard credit lab (Profile E — ADR 0016, lab-only).

Two in-memory shard DBs: debit on source shard, credit on dest, ACK confirm.
No live mesh / no prod 778888 Rocks.

Usage:
  python scripts/cross_shard_lab.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dynamic_sharding import ShardingManager
from storage.database import Database


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _cross_shard_pair(num_shards: int = 4) -> tuple[str, str, int, int]:
    for i in range(200):
        a = f"0x{i:040x}"
        b = f"0x{(i + num_shards * 17):040x}"
        sh = ShardingManager(num_shards=num_shards)
        sa = sh.get_shard_for_address(a)
        sb = sh.get_shard_for_address(b)
        if sa != sb:
            return a, b, sa, sb
    raise RuntimeError("no cross-shard pair found")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db0 = Database(str(base / "shard0.db"))
        db0.initialize()
        db1 = Database(str(base / "shard1.db"))
        db1.initialize()

        sender, recipient, from_shard, to_shard = _cross_shard_pair(2)
        db0.set_balance(sender, 100.0)

        src = ShardingManager(
            num_shards=2,
            db=db0,
            assigned_shard_id=from_shard,
            node_id="lab-shard-src",
            mode="distributed",
        )
        dst = ShardingManager(
            num_shards=2,
            db=db1,
            assigned_shard_id=to_shard,
            node_id="lab-shard-dst",
            mode="distributed",
        )

        _, tx_id = src.add_transaction(
            {"from": sender, "to": recipient, "value": 25.0, "nonce": 0}
        )
        if not tx_id:
            return _fail("cross-shard tx_id missing")
        if src.cross_shard_txs[tx_id].status != "debited":
            return _fail("source must debit before export")
        if db0.get_balance(sender) != 75.0:
            return _fail("sender balance after debit")
        if db1.get_balance(recipient) != 0.0:
            return _fail("recipient must be zero before credit")

        payload = src.export_cross_shard_payload(tx_id)
        if not payload:
            return _fail("export_cross_shard_payload empty")
        if dst.receive_cross_shard_credit(payload) is not True:
            return _fail("receive_cross_shard_credit must succeed")
        if db1.get_balance(recipient) != 25.0:
            return _fail("recipient balance after credit")

        ack = {"tx_id": tx_id, "to_shard": to_shard, "status": "confirmed"}
        if src.receive_cross_shard_ack(ack) is not True:
            return _fail("receive_cross_shard_ack must succeed")
        if src.cross_shard_txs[tx_id].status != "confirmed":
            return _fail("tx must reach confirmed")

        db0.close()
        db1.close()

    print("OK: cross_shard_lab PASS (2-DB debit/credit/ACK; Profile E; not prod mesh)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
