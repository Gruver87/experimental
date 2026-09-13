#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EVM + mempool high-load harness (industrial — not /health/live).

Exercises ChainApplyQueue under concurrent mempool enqueue + forge_and_apply
with mixed simple transfers and EVM deploy txs.

Usage (repo root):
  python scripts/evm_mempool_load_harness.py
  python scripts/evm_mempool_load_harness.py --rounds 40 --workers 8

Exit 0 = PASS. Writes JSON summary to data/evm_mempool_load_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blockchain.mempool import Mempool, MempoolTransaction
from core.blockchain import Blockchain, Transaction
from core.chain_apply_queue import ChainApplyQueue
from execution.evm_adapter import EVMAdapter
from kernel.event_bus import EventBus
from runtime.config import Config
from storage.database import Database


# PUSH1 7 PUSH1 0 SSTORE STOP — tiny deploy runtime
_EVM_DEPLOY_HEX = "600760005500"


def _mk_env(tmp: str) -> tuple:
    path = os.path.join(tmp, "load.db")
    cfg = Config()
    cfg.db_path = path
    cfg.miner_address = "0x" + "f" * 40
    cfg.burn_address = "0x" + "d" * 40
    cfg.evm_enabled = True
    cfg.require_signatures = False
    cfg.max_tx_per_block = 32
    cfg.chain_apply_queue_max = 128
    cfg.chain_apply_timeout_sec = 60.0
    db = Database(path)
    db.initialize()
    bus = EventBus()
    bc = Blockchain(cfg, db, bus)
    bc.evm = EVMAdapter(db, cfg)
    mp = Mempool(max_size=10_000, min_fee=0.0)
    aq = ChainApplyQueue(
        bc,
        maxsize=int(cfg.chain_apply_queue_max),
        timeout_sec=float(cfg.chain_apply_timeout_sec),
    )
    sender = "0x" + "a1" * 20
    recv = "0x" + "b2" * 20
    db.set_balance(sender, 1_000_000.0)
    db.set_balance(cfg.miner_address, 0.0)
    return cfg, db, bc, mp, aq, sender, recv


def _enqueue_batch(
    mp: Mempool,
    sender: str,
    recv: str,
    start_nonce: int,
    n: int,
    *,
    mix_evm: bool,
) -> int:
    added = 0
    for i in range(n):
        nonce = start_nonce + i
        if mix_evm and (i % 3 == 2):
            tx = MempoolTransaction(
                tx_hash=f"evm-{nonce:08x}",
                from_addr=sender,
                to_addr="0x" + "0" * 40,
                amount=0.0,
                fee=0.001,
                nonce=nonce,
                timestamp=time.time(),
                data=_EVM_DEPLOY_HEX,
                gas=500_000,
            )
        else:
            tx = MempoolTransaction(
                tx_hash=f"simple-{nonce:08x}",
                from_addr=sender,
                to_addr=recv,
                amount=0.01,
                fee=0.001,
                nonce=nonce,
                timestamp=time.time(),
                gas=21_000,
            )
        if mp.add(tx):
            added += 1
    return added


def _to_chain_txs(pending) -> list:
    out = []
    for mp_tx in pending:
        out.append(
            Transaction(
                from_addr=mp_tx.from_addr,
                to_addr=mp_tx.to_addr,
                value=mp_tx.amount,
                nonce=mp_tx.nonce,
                gas=int(getattr(mp_tx, "gas", 0) or 21_000),
                data=getattr(mp_tx, "data", "") or "",
                timestamp=int(mp_tx.timestamp),
                tx_hash=mp_tx.tx_hash,
            )
        )
    return out


def run_harness(
    *,
    rounds: int = 20,
    workers: int = 4,
    batch: int = 8,
    mix_evm: bool = True,
) -> dict:
    tmp = tempfile.mkdtemp(prefix="abs_evm_load_")
    cfg, db, bc, mp, aq, sender, recv = _mk_env(tmp)
    errors: list[str] = []
    forged = 0
    forged_fail = 0
    enqueued = 0
    included_tx = 0
    empty_blocks = 0
    nonce_lock = threading.Lock()
    next_nonce = 0
    start_h = bc.get_height()
    t0 = time.perf_counter()

    def producer(_wid: int) -> int:
        nonlocal next_nonce, enqueued
        with nonce_lock:
            base = next_nonce
            next_nonce += batch
        n = _enqueue_batch(mp, sender, recv, base, batch, mix_evm=mix_evm)
        with nonce_lock:
            enqueued += n
        return n

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for r in range(rounds):
                futs = [pool.submit(producer, i) for i in range(workers)]
                for f in as_completed(futs):
                    try:
                        f.result()
                    except Exception as exc:
                        errors.append(f"producer: {exc}")

                pending = mp.get_for_block(int(cfg.max_tx_per_block), db.get_nonce)
                if not pending:
                    continue
                txs = _to_chain_txs(pending)
                ok, block = aq.submit_forge_and_apply(txs, cfg.miner_address, None)
                if ok and block is not None:
                    forged += 1
                    n_inc = len(getattr(block, "transactions", None) or [])
                    included_tx += n_inc
                    if n_inc == 0:
                        empty_blocks += 1
                    for tx in block.transactions:
                        mp.remove(tx.hash)
                else:
                    forged_fail += 1
                    if aq.reject_total:
                        # fail-loud visibility under backpressure
                        pass
    finally:
        aq.stop()

    elapsed = time.perf_counter() - t0
    end_h = bc.get_height()
    tip = db.get_last_block() or {}
    report = {
        "ok": (not errors) and forged > 0 and end_h > start_h and forged_fail == 0,
        "elapsed_sec": round(elapsed, 3),
        "start_height": start_h,
        "end_height": end_h,
        "height_delta": end_h - start_h,
        "enqueued": enqueued,
        "forged_ok": forged,
        "forged_fail": forged_fail,
        "included_tx": included_tx,
        "empty_blocks": empty_blocks,
        "apply_reject_total": int(aq.reject_total),
        "apply_completed_total": int(aq.completed_total),
        "apply_wait_seconds_total": round(float(aq.wait_seconds_total), 4),
        "recv_balance": float(db.get_balance(recv)),
        "tip_hash": str(tip.get("hash", ""))[:16],
        "errors": errors[:20],
        "tmp": tmp,
        "node_version": cfg.node_version,
    }
    report["ok"] = bool(
        report["ok"]
        and report["height_delta"] >= 1
        and report["recv_balance"] > 0
        and report["included_tx"] > 0
        and report["empty_blocks"] == 0
        and not report["errors"]
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="EVM/mempool industrial load harness")
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--no-evm", action="store_true", help="simple transfers only")
    ap.add_argument(
        "--json-out",
        default=str(ROOT / "data" / "evm_mempool_load_report.json"),
    )
    args = ap.parse_args()

    print(
        f"EVM/mempool load harness rounds={args.rounds} workers={args.workers} "
        f"batch={args.batch} mix_evm={not args.no_evm}"
    )
    report = run_harness(
        rounds=args.rounds,
        workers=args.workers,
        batch=args.batch,
        mix_evm=not args.no_evm,
    )
    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "tmp"}, indent=2))
    print(f"Report: {out}")
    if not report["ok"]:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
