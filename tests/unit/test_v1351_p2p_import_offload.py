#!/usr/bin/env python3
"""v1.3.51: P2P/sync import_block off the asyncio event loop."""

from __future__ import annotations

import asyncio
import inspect
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.p2p_node import P2PNode


def test_async_helpers_exist():
    assert hasattr(P2PNode, "_import_block_async")
    assert hasattr(P2PNode, "_reorg_and_import_async")
    assert inspect.iscoroutinefunction(P2PNode._import_block_async)
    assert inspect.iscoroutinefunction(P2PNode._reorg_and_import_async)


def test_hot_paths_do_not_call_blockchain_import_synchronously():
    src = Path("network/p2p_node.py").read_text(encoding="utf-8")
    # Hot async handlers must use offload helpers, not bare blockchain.import_block.
    handle = src.split("async def _handle_new_block", 1)[1].split(
        "async def _handle_get_blocks", 1
    )[0]
    get_blocks = src.split("async def _handle_get_blocks", 1)[1].split(
        "def _get_blocks_future_refuse_reason", 1
    )[0]
    sync = src.split("async def _sync_with_peer", 1)[1].split(
        "async def _reconcile_to_head_hash", 1
    )[0]
    reconcile = src.split("async def _reconcile_to_head_hash", 1)[1].split(
        "async def _reconcile_fork_at_peer", 1
    )[0]
    assert "blockchain.import_block(" not in handle
    assert "_import_block_async" in handle
    assert "asyncio.to_thread(_load_range)" in get_blocks
    # ADR 0004: ahead catch-up is CatchUpPathAService via asyncio.to_thread
    # (imports run off the event loop inside the worker thread).
    assert "blockchain.import_block(" not in sync
    assert "CatchUpPathAService" in sync
    assert "asyncio.to_thread" in sync
    # ADR 0005: reconcile delegates to ForkReconcileService; reorg offload
    # lives in fork_adapters → _reorg_and_import_async.
    assert "blockchain.import_block(" not in reconcile
    assert "_fork_reconcile_run_to_head" in reconcile
    adapters = Path("network/fork_adapters.py").read_text(encoding="utf-8")
    assert "_reorg_and_import_async" in adapters
    assert "asyncio.to_thread(self.sync_engine.fast_sync)" in Path(
        "main.py"
    ).read_text(encoding="utf-8")


def test_import_offload_keeps_event_loop_responsive():
    async def _run():
        cfg = MagicMock()
        cfg.bootstrap_peers = []
        cfg.p2p_max_messages_per_sec = 0
        cfg.p2p_rate_limit_strikes = 5
        cfg.p2p_ban_seconds = 300
        # MagicMock attrs are truthy; pin transport/TLS off for this offload unit test.
        cfg.p2p_native_transport = False
        cfg.p2p_tls_enabled = False
        cfg.require_native_crypto = False
        cfg.deployment_mode = "dev"
        bc = MagicMock()
        mp = MagicMock()

        def slow_import(_data):
            time.sleep(0.25)
            return True

        node = P2PNode(cfg, bc, mp, bus=None)
        node.import_block = slow_import  # type: ignore[method-assign]
        started = time.perf_counter()
        ticks = 0

        async def ticker():
            nonlocal ticks
            while time.perf_counter() - started < 0.2:
                ticks += 1
                await asyncio.sleep(0)

        import_task = asyncio.create_task(node._import_block_async({"height": 1}))
        tick_task = asyncio.create_task(ticker())
        ok, _ = await asyncio.gather(import_task, tick_task)
        assert ok is True
        assert ticks >= 5
        assert int(node._import_offload_total) >= 1

    asyncio.run(_run())


def test_get_blocks_range_fetch_keeps_event_loop_responsive():
    async def _run():
        from crypto import native
        from network.p2p_node import MSG_BLOCKS, PeerConnection
        from runtime.config import Config
        from unittest.mock import AsyncMock

        class _FakeWriter:
            def write(self, _data):
                return None

            async def drain(self):
                return None

            def close(self):
                return None

            def get_extra_info(self, _name, default=None):
                return default

            def is_closing(self):
                return False

        class _FakeReader:
            async def read(self, _n):
                await asyncio.sleep(0)
                return b""

        cfg = Config()
        cfg.p2p_native_transport = False
        cfg.require_native_crypto = False
        cfg.deployment_mode = "dev"
        cfg.bootstrap_peers = []
        cfg.sync_batch_size = 8
        bc = MagicMock()
        bc.get_height.return_value = 3

        def slow_get(h):
            time.sleep(0.05)
            return {"height": int(h), "hash": "aa" * 32}

        bc.get_block.side_effect = slow_get
        node = P2PNode(cfg, bc, MagicMock(), bus=None)
        peer = PeerConnection(_FakeReader(), _FakeWriter())
        peer.peer_id = "p1"
        peer.send = AsyncMock(return_value=True)  # type: ignore
        orig = native.validate_p2p_get_blocks_payload
        started = time.perf_counter()
        ticks = 0

        async def ticker():
            nonlocal ticks
            while time.perf_counter() - started < 0.15:
                ticks += 1
                await asyncio.sleep(0)

        try:
            native.validate_p2p_get_blocks_payload = (  # type: ignore
                lambda _d: {"from_height": 1, "to_height": 3}
            )
            fetch_task = asyncio.create_task(
                node._handle_get_blocks(peer, {"from_height": 1, "to_height": 3})
            )
            tick_task = asyncio.create_task(ticker())
            await asyncio.gather(fetch_task, tick_task)
        finally:
            native.validate_p2p_get_blocks_payload = orig  # type: ignore
        assert ticks >= 5
        peer.send.assert_called()
        assert peer.send.call_args[0][0] == MSG_BLOCKS

    asyncio.run(_run())
