#!/usr/bin/env python3
"""Cross-shard credit lab (Profile E — ADR 0016, lab-only).

Wave-1: two-DB debit → credit → ACK confirm.
Wave-2: 2/3 validator committee quorum before confirmed.

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


def _wave1_simple_ack(tmp: Path) -> int:
    db0 = Database(str(tmp / "shard0.db"))
    db0.initialize()
    db1 = Database(str(tmp / "shard1.db"))
    db1.initialize()
    try:
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
    finally:
        db0.close()
        db1.close()
    return 0


def _wave2_validator_quorum(tmp: Path) -> int:
    db0 = Database(str(tmp / "q0.db"))
    db0.initialize()
    db1 = Database(str(tmp / "q1.db"))
    db1.initialize()
    try:
        sender, recipient, from_shard, to_shard = _cross_shard_pair(2)
        db0.set_balance(sender, 50.0)

        committees = {
            from_shard: ["src-v1", "src-v2", "src-v3"],
            to_shard: ["dst-v1", "dst-v2", "dst-v3"],
        }
        src = ShardingManager(
            num_shards=2,
            db=db0,
            assigned_shard_id=from_shard,
            node_id="shard-src",
            validator_id="src-v1",
            mode="distributed",
        )
        src.load_shard_committees(committees)
        dst = ShardingManager(
            num_shards=2,
            db=db1,
            assigned_shard_id=to_shard,
            node_id="shard-dst",
            validator_id="dst-v1",
            mode="distributed",
        )
        dst.load_shard_committees(committees)

        _, tx_id = src.add_transaction(
            {"from": sender, "to": recipient, "value": 10.0, "nonce": 0}
        )
        if not tx_id:
            return _fail("quorum tx_id missing")
        if src.cross_shard_txs[tx_id].status != "debited":
            return _fail("quorum source must debit")
        if src.coordinator.quorum_reached(tx_id) is not False:
            return _fail("quorum must be false with single local ack")

        src.coordinator.record_validator_ack(tx_id, from_shard, "src-v2")
        if src.coordinator.quorum_reached(tx_id) is not False:
            return _fail("source committee alone must not finalize dest quorum")

        payload = src.export_cross_shard_payload(tx_id)
        if dst.receive_cross_shard_credit(payload) is not True:
            return _fail("quorum credit failed")
        if db1.get_balance(recipient) != 10.0:
            return _fail("quorum recipient balance")

        src.receive_cross_shard_ack(
            {"tx_id": tx_id, "shard_id": to_shard, "validator_id": "dst-v1"}
        )
        if src.coordinator.quorum_reached(tx_id) is not False:
            return _fail("one dest ack must not reach 2/3")

        if (
            src.receive_cross_shard_ack(
                {"tx_id": tx_id, "shard_id": to_shard, "validator_id": "dst-v2"}
            )
            is not True
        ):
            return _fail("second dest ack must confirm")
        if src.cross_shard_txs[tx_id].status != "confirmed":
            return _fail("quorum path must confirm")
    finally:
        db0.close()
        db1.close()
    return 0


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        rc = _wave1_simple_ack(base)
        if rc != 0:
            return rc
        rc = _wave2_validator_quorum(base)
        if rc != 0:
            return rc

    print("OK: cross_shard_lab PASS (simple ACK + 2/3 validator quorum; Profile E)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
