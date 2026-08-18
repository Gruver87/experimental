#!/usr/bin/env python3
"""Empty follower tip must import leader genesis at height 0 (not skip as already-at-head)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.blockchain import Block
from sync.catchup.engine_io import SyncEngineCatchUpIO
from sync.catchup.path_a import CatchUpPathAService
from sync.catchup.types import CatchUpConfig, CatchUpPeerView, CatchUpStatus
from sync.sync_engine import SyncEngine


GENESIS_PARENT = "0" * 64


def _genesis_block() -> dict:
    block = Block(
        height=0,
        parent_hash=GENESIS_PARENT,
        miner="genesis",
        transactions=[],
        timestamp=1_700_000_000,
        state_root="a" * 64,
    )
    return block.to_dict()


def test_fast_sync_does_not_skip_empty_tip_at_height_zero():
    genesis = _genesis_block()
    head = genesis["hash"]

    class _EmptyChain:
        def get_height(self):
            return 0

        def get_last_block(self):
            return None

        def get_state_root(self):
            return ""

        def get_block(self, _h):
            return None

        def get_block_by_hash(self, _h):
            return None

    peer = SimpleNamespace(peer_id="leader", head=head, height=0)
    p2p = SimpleNamespace(
        peers={"leader": peer},
        _state_consistent=False,
        _running=True,
        request_peer_state_roots_sync=lambda timeout=15: [
            {"peer_id": "leader", "height": 0, "state_root": "a" * 64, "head_hash": head}
        ],
    )
    node = SimpleNamespace(
        p2p=p2p,
        blockchain=_EmptyChain(),
        consensus=None,
        import_block=MagicMock(return_value=True),
    )
    eng = SyncEngine(node=node)
    eng._resolve_block = lambda h: genesis if h == head else None  # type: ignore[method-assign]

    assert eng._local_needs_genesis() is True
    ok = eng.fast_sync()
    assert node.import_block.called
    imported = node.import_block.call_args[0][0]
    assert int(imported.get("height", -1)) == 0
    assert imported.get("hash") == head
    assert ok is True or eng._last_sync_error in ("", "state_sync_failed")


def test_path_a_imports_genesis_when_needs_genesis():
    genesis = _genesis_block()
    head = genesis["hash"]

    class _IO:
        def __init__(self):
            self._imported = []

        def height(self):
            return 0

        def needs_genesis(self):
            return True

        def head(self):
            return ""

        def expected_parent(self, height: int):
            return GENESIS_PARENT if int(height) <= 0 else ""

        def get_block(self, _key):
            return None

        def import_block(self, data):
            self._imported.append(dict(data))
            return True

        def find_ancestor_height(self, _ph):
            return None

        def reorg_to_ancestor(self, _h):
            return False

        def fetch_blocks(self, _pid, from_h, to_h, _parent, timeout=45.0):
            if int(from_h) == 0 and int(to_h) >= 0:
                return [genesis]
            return []

        def local_tip_probe_refuse(self, _peer):
            return ""

        def peer_head_probe_refuse(self, _peer):
            return ""

        def bump_refuse(self, _reason):
            return None

        def note_import_fail(self, _pid):
            return None

        def on_progress(self, _msg):
            return None

        def set_peer_height(self, _pid, _h):
            return None

        def is_running(self):
            return True

        def batch_size(self):
            return 32

    io = _IO()
    svc = CatchUpPathAService(chain=io, fetch=io, probe=io, side=io)
    peer = CatchUpPeerView(peer_id="leader", height=0, head_hash=head)
    outcome = svc.run_ahead(peer, CatchUpConfig(batch_size=8, require_head=True))
    assert outcome.status is CatchUpStatus.COMPLETE or int(outcome.imported or 0) >= 1
    assert io._imported and int(io._imported[0]["height"]) == 0


def test_engine_io_includes_genesis_in_ahead_index():
    genesis = _genesis_block()
    head = genesis["hash"]

    class _EmptyChain:
        def get_height(self):
            return 0

        def get_last_block(self):
            return None

        def get_block(self, _h):
            return None

        def get_block_by_hash(self, _h):
            return None

    node = SimpleNamespace(blockchain=_EmptyChain(), import_block=lambda b: True)
    eng = SyncEngine(node=node)
    eng._resolve_block = lambda h: genesis if h == head else None  # type: ignore[method-assign]
    io = SyncEngineCatchUpIO(
        eng,
        peer_id="leader",
        peer_head=head,
        target_height=0,
        batch_size=8,
        running=True,
    )
    assert io.needs_genesis() is True
    batch = io.fetch_blocks("leader", 0, 0, GENESIS_PARENT, timeout=5.0)
    assert batch is not None
    assert len(batch) == 1
    assert int(batch[0]["height"]) == 0


def test_engine_io_store_error_at_empty_tip_needs_genesis():
    class _BoomChain:
        def get_height(self):
            return 0

        def get_last_block(self):
            raise RuntimeError("store down")

        def get_block(self, _h):
            return None

        def get_block_by_hash(self, _h):
            return None

    class _Eng:
        def __init__(self):
            self.node = SimpleNamespace(blockchain=_BoomChain())

        def _local_height(self):
            return 0

    io = SyncEngineCatchUpIO(
        _Eng(),
        peer_id="leader",
        peer_head="aa" * 32,
        target_height=0,
        batch_size=8,
        running=True,
    )
    assert io.needs_genesis() is True


def test_engine_io_store_error_at_nonempty_does_not_force_genesis():
    class _BoomChain:
        def get_height(self):
            return 42

        def get_last_block(self):
            raise RuntimeError("store down")

        def get_block(self, _h):
            return None

        def get_block_by_hash(self, _h):
            return None

    class _Eng:
        def __init__(self):
            self.node = SimpleNamespace(blockchain=_BoomChain())

        def _local_height(self):
            return 42

    io = SyncEngineCatchUpIO(
        _Eng(),
        peer_id="leader",
        peer_head="aa" * 32,
        target_height=50,
        batch_size=8,
        running=True,
    )
    assert io.needs_genesis() is False
