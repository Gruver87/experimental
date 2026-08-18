#!/usr/bin/env python3
"""ADR 0004 Step C — SyncEngine.fast_sync shares CatchUpPathAService ports."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.blockchain import Block
from sync.catchup.engine_io import SyncEngineCatchUpIO
from sync.sync_engine import SyncEngine


class _BlockChain:
    def __init__(self, height, blocks_by_hash):
        self._height = height
        self._blocks = blocks_by_hash

    def get_height(self):
        return self._height

    def get_state_root(self):
        return "s" * 64

    def get_block_by_hash(self, h):
        return self._blocks.get(h)

    def get_block(self, height):
        for b in self._blocks.values():
            if int(b.get("height", 0)) == height:
                return b
        return None


class _Peer:
    def __init__(self, head, height=0, peer_id="p1"):
        self.head = head
        self.height = height
        self.peer_id = peer_id


class _P2P:
    def __init__(self, peers):
        self.peers = {p.peer_id: p for p in peers}
        self._state_consistent = False
        self._running = True

    def request_peer_state_roots_sync(self, timeout=15):
        return [
            {
                "peer_id": peer_id,
                "height": int(getattr(peer, "height", 0) or 0),
                "state_root": "s" * 64,
            }
            for peer_id, peer in self.peers.items()
        ]


class _Node:
    def __init__(self, peers, blockchain, imported=None, fail_height=None):
        self.p2p = _P2P(peers)
        self.blockchain = blockchain
        self.consensus = None
        self._imported = imported if imported is not None else []
        self._fail_height = fail_height

    def import_block(self, block):
        if int(block.get("height", 0)) == self._fail_height:
            return False
        self._imported.append(block)
        h = int(block.get("height", 0) or 0)
        if h > int(self.blockchain.get_height()):
            self.blockchain._height = h
        return True

    def request_peer_state_roots_sync(self, timeout=15):
        return self.p2p.request_peer_state_roots_sync(timeout=timeout)

    def get_height(self):
        return self.blockchain.get_height()


def _chain_blocks():
    blocks = {}
    prev = "0" * 64
    for h in range(9):
        block = Block(
            height=h,
            parent_hash=prev,
            miner="0x" + "1" * 40,
            transactions=[],
            timestamp=1000 + h,
            state_root="s" * 64,
        )
        data = block.to_dict()
        blocks[data["hash"]] = data
        prev = data["hash"]
    return blocks


def _head_hash(blocks, height=8):
    return [b for b in blocks.values() if int(b["height"]) == height][0]["hash"]


def test_fast_sync_uses_catchup_path_a_service():
    """Source wiring: fast_sync must call CatchUpPathAService, not a private import loop."""
    src = (ROOT / "sync" / "sync_engine.py").read_text(encoding="utf-8")
    assert "CatchUpPathAService" in src
    assert "SyncEngineCatchUpIO" in src
    assert "svc.run_ahead" in src
    # The old private import for-loop body must be gone from fast_sync.
    assert "Downloaded chain is not contiguous" in src  # still reported via IO
    # Ensure we no longer drive import solely via enumerate(to_import) in fast_sync.
    assert "for i, block in enumerate(to_import)" not in src


def test_engine_io_serves_height_batches_via_download_chain():
    blocks = _chain_blocks()
    bc = _BlockChain(height=5, blocks_by_hash=blocks)
    peer = _Peer(_head_hash(blocks), height=8, peer_id="p1")
    node = _Node([peer], bc)
    engine = SyncEngine(node=node)
    io = SyncEngineCatchUpIO(
        engine,
        peer_id="p1",
        peer_head=_head_hash(blocks),
        target_height=8,
        batch_size=2,
    )
    batch = io.fetch_blocks("p1", 6, 7, parent_hash=_head_hash(blocks, 5), timeout=5.0)
    assert batch is not None
    assert [int(b["height"]) for b in batch] == [6, 7]
    assert len(io.fetch_calls) == 1


def test_engine_io_rejects_non_contiguous_before_serving():
    blocks = _chain_blocks()
    bad = [b for b in blocks.values() if int(b["height"]) == 7][0]
    bad["parent_hash"] = bad["parent_hash"] + "broken"
    bc = _BlockChain(height=5, blocks_by_hash=blocks)
    peer = _Peer(_head_hash(blocks), height=8, peer_id="p1")
    node = _Node([peer], bc)
    engine = SyncEngine(node=node)
    io = SyncEngineCatchUpIO(
        engine,
        peer_id="p1",
        peer_head=_head_hash(blocks),
        target_height=8,
    )
    out = io.fetch_blocks("p1", 6, 8, parent_hash="x", timeout=5.0)
    assert out is None
    assert io._chain_error == "non_contiguous_chain"


def test_shared_path_fast_sync_imports_new_blocks():
    blocks = _chain_blocks()
    bc = _BlockChain(height=5, blocks_by_hash=blocks)
    imported = []
    peer = _Peer(_head_hash(blocks), height=8, peer_id="p1")
    node = _Node([peer], bc, imported=imported)
    engine = SyncEngine(node=node)
    assert engine.fast_sync() is True
    assert [int(b["height"]) for b in imported] == [6, 7, 8]


def test_shared_path_fast_sync_target_block_incomplete_ahead():
    blocks = _chain_blocks()
    bc = _BlockChain(height=5, blocks_by_hash=blocks)
    imported = []
    peer = _Peer(_head_hash(blocks), height=8, peer_id="p1")
    node = _Node([peer], bc, imported=imported)
    engine = SyncEngine(node=node)
    assert engine.fast_sync(target_block=6) is False
    assert [int(b["height"]) for b in imported] == [6]
    assert engine.consistency.snapshot().reason_code == "incomplete_ahead"


def test_shared_path_fast_sync_import_fail_stops():
    blocks = _chain_blocks()
    bc = _BlockChain(height=5, blocks_by_hash=blocks)
    imported = []
    peer = _Peer(_head_hash(blocks), height=8, peer_id="p1")
    node = _Node([peer], bc, imported=imported, fail_height=7)
    engine = SyncEngine(node=node)
    assert engine.fast_sync() is False
    assert [int(b["height"]) for b in imported] == [6]
    assert engine.is_syncing is False


def test_no_network_import_in_engine_io():
    src = (ROOT / "sync" / "catchup" / "engine_io.py").read_text(encoding="utf-8")
    assert "import network" not in src
    assert "from network" not in src
    # Literal import path must not appear as an import statement.
    assert "from network.p2p_node" not in src
    assert "import network.p2p_node" not in src


def test_engine_io_peer_head_probe_refuses_hash_mismatch():
    from sync.catchup.types import CatchUpPeerView

    blocks = _chain_blocks()
    head = _head_hash(blocks, 8)
    bc = _BlockChain(height=5, blocks_by_hash=blocks)
    peer = _Peer(head, height=8, peer_id="p1")
    node = _Node([peer], bc)
    engine = SyncEngine(node=node)
    io = SyncEngineCatchUpIO(
        engine, peer_id="p1", peer_head=head, target_height=8
    )
    io._chain_ready = True
    io._chain_ok = True
    io._by_height = {
        8: {"height": 8, "hash": "ff" * 32, "parent_hash": "00" * 32},
    }
    view = CatchUpPeerView(peer_id="p1", height=8, head_hash=head)
    assert io.peer_head_probe_refuse(view) == "catch_up_peer_head_hash_mismatch"


def test_engine_io_tip_probe_refuses_parent_mismatch():
    from sync.catchup.types import CatchUpPeerView

    blocks = _chain_blocks()
    head = _head_hash(blocks, 8)
    tip = [b for b in blocks.values() if int(b["height"]) == 5][0]
    bc = _BlockChain(height=5, blocks_by_hash=blocks)
    peer = _Peer(head, height=8, peer_id="p1")
    node = _Node([peer], bc)
    engine = SyncEngine(node=node)
    io = SyncEngineCatchUpIO(
        engine, peer_id="p1", peer_head=head, target_height=8
    )
    io._chain_ready = True
    io._chain_ok = True
    io._by_height = {
        6: {"height": 6, "hash": "b6" * 32, "parent_hash": "ee" * 32},
    }
    view = CatchUpPeerView(peer_id="p1", height=8, head_hash=head)
    assert io.head() == tip["hash"]
    assert io.local_tip_probe_refuse(view) == "catch_up_tip_head_mismatch"
