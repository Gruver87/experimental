#!/usr/bin/env python3
"""v1.3.66: load / backpressure industrial fixes."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from concurrent.futures import Future

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.chain_apply_queue import ApplyOpKind, ChainApplyQueue, _Job, _PriItem


class _FakeBC:
    def import_block(self, data):
        time.sleep(0.05)
        return True


def test_apply_queue_expires_stale_jobs():
    q = ChainApplyQueue(_FakeBC(), maxsize=8, timeout_sec=0.01, name="t66")
    try:
        fut = Future()
        job = _Job(
            kind=ApplyOpKind.IMPORT,
            future=fut,
            payload={},
            deadline_monotonic=time.monotonic() - 1.0,
        )
        q._q.put_nowait(_PriItem(priority=4, seq=1, job=job))
        time.sleep(0.2)
        assert fut.done()
        assert fut.result()[0] == "expired"
        assert q.expired_total >= 1
    finally:
        q.stop()


def test_needles_wave2():
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "drop mempool txs only after successful import" in p2p
    assert "_schedule_sync" in p2p
    assert "_schedule_connect" in p2p
    assert "_send_q" in p2p
    rocks = (ROOT / "storage" / "rocks_store.py").read_text(encoding="utf-8")
    assert 'key_meta("chain_tip")' in rocks
    assert "prefix_last" in rocks
    rust = (ROOT / "native" / "abs_native" / "src" / "storage" / "mod.rs").read_text(
        encoding="utf-8"
    )
    assert "fn prefix_last" in rust
    assert "fn prefix_prev" in rust
    assert "fn scan_range" in rust
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_chain_apply_expired_total" in metrics
