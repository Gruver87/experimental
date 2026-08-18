#!/usr/bin/env python3
"""v1.3.52: serial ChainApplyQueue — mine and import share one worker."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.chain_apply_queue import ChainApplyQueue


def test_queue_serializes_ops():
    order = []
    lock = threading.Lock()

    class FakeBC:
        def create_block(self, txs, proposer):
            with lock:
                order.append("create")
            time.sleep(0.05)
            blk = MagicMock()
            blk.height = 1
            blk.hash = "h1"
            blk.transactions = txs
            return blk

        def add_block(self, block):
            with lock:
                order.append("add")
            time.sleep(0.05)
            return True

        def import_block(self, data):
            with lock:
                order.append("import")
            time.sleep(0.05)
            return True

    q = ChainApplyQueue(FakeBC(), maxsize=8, timeout_sec=5.0)
    try:
        results = []

        def forge():
            ok, _ = q.submit_forge_and_apply([], "p")
            results.append(("forge", ok))

        def imp():
            ok = q.submit_import({"height": 1})
            results.append(("import", ok))

        t1 = threading.Thread(target=forge)
        t2 = threading.Thread(target=imp)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert all(ok for _, ok in results)
        # No interleave of create/add with import mid-forge
        joined = "".join(order)
        assert "createadd" in joined or joined.startswith("import")
        if "create" in joined and "add" in joined:
            assert joined.index("create") < joined.index("add")
            # import must not sit between create and add
            c, a = joined.index("create"), joined.index("add")
            mid = joined[c + len("create") : a]
            assert "import" not in mid
    finally:
        q.stop()


def test_backpressure_reject():
    class SlowBC:
        def import_block(self, data):
            time.sleep(0.4)
            return True

    q = ChainApplyQueue(SlowBC(), maxsize=1, timeout_sec=5.0)
    try:
        t1 = threading.Thread(target=lambda: q.submit_import({"i": 1}))
        t1.start()
        time.sleep(0.05)
        t2 = threading.Thread(target=lambda: q.submit_import({"i": 2}))
        t2.start()
        time.sleep(0.05)
        ok = q.submit_import({"i": 3})
        assert ok is False
        assert q.reject_total >= 1
        t1.join(timeout=5)
        t2.join(timeout=5)
    finally:
        q.stop()


def test_wiring():
    main = Path("main.py").read_text(encoding="utf-8")
    assert "ChainApplyQueue" in main
    assert "submit_forge_and_apply_async" in main
    assert "await self.p2p._broadcast_block" in main
    p2p = Path("network/p2p_node.py").read_text(encoding="utf-8")
    assert "apply_queue" in p2p
    assert "note_local_forge" in p2p
    note_i = main.find("note(1.0, height=")
    bcast_i = main.find("await self.p2p._broadcast_block")
    assert 0 <= note_i < bcast_i
    assert "submit_import_async" in p2p or "submit_import" in p2p
    assert Path("core/chain_apply_queue.py").is_file()


def test_busy_true_during_dispatch():
    started = threading.Event()
    release = threading.Event()

    class SlowBC:
        def import_block(self, data):
            started.set()
            assert release.wait(timeout=2.0)
            return True

    q = ChainApplyQueue(SlowBC(), maxsize=4, timeout_sec=5.0, name="tbusy")
    try:
        worker = threading.Thread(target=lambda: q.submit_import({"h": 1}), daemon=True)
        worker.start()
        assert started.wait(timeout=2.0)
        assert q.busy is True
        release.set()
        worker.join(timeout=3.0)
        assert q.busy is False
    finally:
        q.stop()


def test_async_overflow_returns_immediately():
    import asyncio

    class SlowBC:
        def import_block(self, data):
            time.sleep(0.4)
            return True

    async def _run() -> None:
        q = ChainApplyQueue(SlowBC(), maxsize=1, timeout_sec=30.0, name="tasync")
        try:
            t0 = time.perf_counter()
            first = asyncio.create_task(q.submit_import_async({"i": 1}))
            await asyncio.sleep(0.05)
            second = asyncio.create_task(q.submit_import_async({"i": 2}))
            await asyncio.sleep(0.05)
            third = await q.submit_import_async({"i": 3})
            elapsed = time.perf_counter() - t0
            assert third is False
            assert elapsed < 1.0
            assert q.reject_total >= 1
            await first
            await second
        finally:
            q.stop()

    asyncio.run(_run())


def test_async_submit_uses_wrap_future_not_to_thread():
    src = Path("core/chain_apply_queue.py").read_text(encoding="utf-8")
    assert "asyncio.wrap_future" in src
    assert "asyncio.to_thread(self.submit_import" not in src
    p2p = Path("network/p2p_node.py").read_text(encoding="utf-8")
    assert "Saturated apply queue" in p2p
