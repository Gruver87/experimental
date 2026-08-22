#!/usr/bin/env python3
"""Unit tests for SyncSolicitHub (ADR 0003 Step C / D — waiter evacuation)."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sync.ports import SyncSolicitPort
from sync.solicit import (
    MSG_BLOCK,
    MSG_BLOCKS,
    MSG_MEMPOOL,
    MSG_PEERS,
    MSG_STATE_ROOT_RESPONSE,
    SyncSolicitHub,
)


class _Peer:
    def __init__(self, peer_id: str = "peer-1") -> None:
        self.peer_id = peer_id


class _Fut:
    def __init__(self) -> None:
        self._done = False
        self.result = None

    def done(self) -> bool:
        return self._done

    def set_result(self, value: Any) -> None:
        self.result = value
        self._done = True


def test_hub_implements_solicit_port() -> None:
    hub = SyncSolicitHub()
    assert isinstance(hub, SyncSolicitPort)


def test_no_waiter_passthrough() -> None:
    hub = SyncSolicitHub()
    strikes: list[str] = []
    r = hub.fulfill_or_reject(
        _Peer(),
        MSG_MEMPOOL,
        [],
        {"type": MSG_MEMPOOL, "data": []},
        strike=lambda p, reason: strikes.append(reason) or False,
    )
    assert r.consumed is False
    assert r.detail == "no_waiter"
    assert strikes == []


def test_mempool_fulfill_peer_reply() -> None:
    hub = SyncSolicitHub()
    fut = _Fut()
    hub.arm("peer-1", (MSG_MEMPOOL,), fut, {"kind": "mempool"})
    assert hub.armed_count == 1
    strikes: list[str] = []
    msg = {"type": MSG_MEMPOOL, "data": [{"hash": "x"}]}
    r = hub.fulfill_or_reject(
        _Peer(),
        MSG_MEMPOOL,
        msg["data"],
        msg,
        strike=lambda p, reason: strikes.append(reason) or False,
    )
    assert r.consumed is True
    assert r.detail == "mempool_ok"
    assert fut.result is msg
    assert strikes == []
    assert hub._fulfills_total == 1


def test_blocks_fulfill_peer_reply() -> None:
    hub = SyncSolicitHub(verify_blocks=lambda *_a, **_k: None)
    fut = _Fut()
    hub.arm(
        "peer-1",
        (MSG_BLOCKS,),
        fut,
        {
            "kind": "blocks",
            "from_height": 1,
            "to_height": 2,
            "parent_hash": "aa" * 32,
            "allow_empty": False,
        },
    )
    body = [{"height": 1, "hash": "b1"}, {"height": 2, "hash": "b2"}]
    msg = {"type": MSG_BLOCKS, "data": body}
    r = hub.fulfill_or_reject(
        _Peer(),
        MSG_BLOCKS,
        body,
        msg,
        strike=lambda *_a: False,
    )
    assert r.consumed is True
    assert r.detail == "blocks_ok"
    assert fut.result is msg


def test_wrong_kind_mempool_strikes() -> None:
    hub = SyncSolicitHub()
    fut = _Fut()
    hub.arm("peer-1", (MSG_MEMPOOL,), fut, {"kind": "blocks"})
    strikes: list[str] = []
    r = hub.fulfill_or_reject(
        _Peer(),
        MSG_MEMPOOL,
        [],
        {"type": MSG_MEMPOOL, "data": []},
        strike=lambda p, reason: strikes.append(reason) or False,
        bump=lambda n, d=1: None,
    )
    assert r.consumed is True
    assert "unsolicited_mempool" in strikes
    assert fut.result is None
    assert hub._rejects_total == 1


def test_blocks_semantic_reject() -> None:
    def _verify(*_a, **_k):
        return "bad_blocks_batch"

    hub = SyncSolicitHub(verify_blocks=_verify)
    fut = _Fut()
    hub.arm(
        "peer-1",
        (MSG_BLOCKS,),
        fut,
        {"kind": "blocks", "from_height": 1, "to_height": 2, "parent_hash": ""},
    )
    strikes: list[str] = []
    r = hub.fulfill_or_reject(
        _Peer(),
        MSG_BLOCKS,
        [],
        {"type": MSG_BLOCKS, "data": []},
        strike=lambda p, reason: strikes.append(reason) or False,
        bump=lambda n, d=1: None,
    )
    assert r.consumed is True
    assert strikes == ["bad_blocks_batch"]
    assert fut.result is None


def test_state_root_ok() -> None:
    hub = SyncSolicitHub(verify_state_root=lambda *_a, **_k: None)
    fut = _Fut()
    hub.arm(
        "peer-1",
        (MSG_STATE_ROOT_RESPONSE,),
        fut,
        {"kind": "state_root", "height": 1, "expected_head": ""},
    )
    msg = {
        "type": MSG_STATE_ROOT_RESPONSE,
        "data": {"height": 1, "state_root": "aa" * 32},
    }
    r = hub.fulfill_or_reject(
        _Peer(),
        MSG_STATE_ROOT_RESPONSE,
        msg["data"],
        msg,
        strike=lambda p, reason: False,
    )
    assert r.consumed is True
    assert fut.result is msg


def test_mempool_solicit_armed() -> None:
    hub = SyncSolicitHub()
    assert hub.mempool_solicit_armed("peer-1") is False
    hub.arm("peer-1", (MSG_MEMPOOL,), _Fut(), {"kind": "mempool"})
    assert hub.mempool_solicit_armed("peer-1") is True
    hub.clear("peer-1")
    assert hub.mempool_solicit_armed("peer-1") is False


def test_timeout_fulfills_future_and_clears() -> None:
    hub = SyncSolicitHub()
    fut = _Fut()
    hub.arm("peer-1", (MSG_BLOCKS,), fut, {"kind": "blocks"})
    assert hub.timeout("peer-1") is True
    assert fut.done() is True
    assert fut.result is None
    assert hub.armed_count == 0
    assert hub._timeouts_total == 1
    # Second timeout is a no-op.
    assert hub.timeout("peer-1") is False


def test_expire_stale_clears_old_waiters_keeps_fresh() -> None:
    hub = SyncSolicitHub(default_max_age_sec=30.0)
    old_fut = _Fut()
    new_fut = _Fut()
    now = 1_000.0
    hub.arm("old-peer", (MSG_BLOCK,), old_fut, {"kind": "block"}, armed_at=now - 60.0)
    hub.arm("new-peer", (MSG_BLOCK,), new_fut, {"kind": "block"}, armed_at=now - 5.0)
    cleared = hub.expire_stale(30.0, now=now)
    assert cleared == 1
    assert old_fut.done() is True
    assert old_fut.result is None
    assert new_fut.done() is False
    assert hub.get("new-peer") is not None
    assert hub.get("old-peer") is None
    assert hub._stale_sweeps_total == 1


def test_expire_stale_zero_max_age_sweeps_legacy_unstamped() -> None:
    """Legacy 3-tuple waiters (armed_at=0) expire only when max_age<=0."""
    hub = SyncSolicitHub()
    fut = _Fut()
    # Simulate legacy insert bypassing arm().
    hub.waiters["legacy"] = ((MSG_PEERS,), fut, {"kind": "peers"})
    assert hub.expire_stale(30.0, now=time.monotonic()) == 0
    assert hub.get("legacy") is not None
    assert hub.expire_stale(0.0, now=time.monotonic()) == 1
    assert fut.result is None
    assert hub.get("legacy") is None


def test_clear_all_with_timeout_futures() -> None:
    hub = SyncSolicitHub()
    futs = [_Fut(), _Fut()]
    hub.arm("a", (MSG_MEMPOOL,), futs[0], {"kind": "mempool"})
    hub.arm("b", (MSG_MEMPOOL,), futs[1], {"kind": "mempool"})
    n = hub.clear_all(timeout_futures=True)
    assert n == 2
    assert hub.armed_count == 0
    assert all(f.done() and f.result is None for f in futs)


@pytest.mark.asyncio
async def test_asyncio_future_timeout_path() -> None:
    """Mirrors P2P _wait_peer_response: arm → shielded wait_for → hub.timeout."""
    hub = SyncSolicitHub()
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    hub.arm("peer-1", (MSG_BLOCKS,), fut, {"kind": "blocks"})
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(fut), timeout=0.05)
    hub.timeout("peer-1", result=None)
    assert fut.done()
    assert fut.result() is None
    assert hub.armed_count == 0


@pytest.mark.asyncio
async def test_asyncio_future_peer_reply_unblocks_waiter() -> None:
    hub = SyncSolicitHub(verify_blocks=lambda *_a, **_k: None)
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    hub.arm(
        "peer-1",
        (MSG_BLOCKS,),
        fut,
        {"kind": "blocks", "from_height": 1, "to_height": 1, "parent_hash": ""},
    )

    async def _reply() -> None:
        await asyncio.sleep(0.01)
        msg = {"type": MSG_BLOCKS, "data": [{"height": 1}]}
        hub.fulfill_or_reject(
            _Peer(),
            MSG_BLOCKS,
            msg["data"],
            msg,
            strike=lambda *_a: False,
        )

    task = asyncio.create_task(_reply())
    out = await asyncio.wait_for(fut, timeout=1.0)
    await task
    assert out["type"] == MSG_BLOCKS
    hub.clear("peer-1")


def test_catch_up_policy_ahead() -> None:
    from sync.catchup import CatchUpPolicy

    p = CatchUpPolicy()
    assert (
        p.ahead_refuse_reason(
            local_height=1, peer_height=5, peer_head="", require_head=True
        )
        == "catch_up_no_head"
    )
    assert (
        p.ahead_refuse_reason(
            local_height=5, peer_height=5, peer_head="aa", require_head=True
        )
        == ""
    )


def test_p2p_handle_message_only_forwards_to_hub() -> None:
    src = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "solicit_hub.fulfill_or_reject" in src
    assert "from sync.solicit import SyncSolicitHub" in src
    assert "hub.timeout(" in src
    # No residual inline waiter table mutation in wait path fallbacks.
    assert "self._sync_waiters[peer.peer_id]" not in src
    assert "self._sync_waiters.pop" not in src
    # Dispatcher must not own solicit kind matching (hub does).
    assert "solicit_hub.fulfill_or_reject" in src
    # At most back-compat alias assignment.
    assert src.count("self._sync_waiters = self.solicit_hub.waiters") == 1
    assert "Wait outside the lock" in src
    assert "self._solicit_lock_for(pid, kind)" in src
    assert "if pid and self.peers.get(pid) is not peer" in src
    assert "Isolated node: return immediately" in src
    assert "state_root enqueue does not wait the write Future" in src
    assert "_send_root_q" in src
    assert "_native_write_bound" in src
    assert "_consume_late_state_root" in src
    solicit = (ROOT / "sync" / "solicit.py").read_text(encoding="utf-8")
    assert "Park even when kinds match" in solicit


def test_second_state_root_arm_parks_does_not_overwrite() -> None:
    hub = SyncSolicitHub(verify_state_root=lambda *_a, **_k: None)
    first = _Fut()
    second = _Fut()
    ctx = {"kind": "state_root", "height": 1, "expected_head": ""}
    hub.arm("peer-1", (MSG_STATE_ROOT_RESPONSE,), first, ctx)
    hub.arm("peer-1", (MSG_STATE_ROOT_RESPONSE,), second, ctx)
    assert hub.armed_count == 2
    msg = {
        "type": MSG_STATE_ROOT_RESPONSE,
        "data": {"height": 1, "state_root": "aa" * 32},
    }
    r = hub.fulfill_or_reject(
        _Peer(),
        MSG_STATE_ROOT_RESPONSE,
        msg["data"],
        msg,
        strike=lambda *_a: False,
    )
    assert r.consumed is True
    assert first.result is msg
    assert second.result is msg


def test_timeout_fut_does_not_steal_other_state_root() -> None:
    hub = SyncSolicitHub()
    keep = _Fut()
    drop = _Fut()
    ctx = {"kind": "state_root", "height": 1}
    hub.arm("peer-1", (MSG_STATE_ROOT_RESPONSE,), keep, ctx)
    hub.arm("peer-1", (MSG_STATE_ROOT_RESPONSE,), drop, ctx)
    assert hub.timeout("peer-1", result=None, kind="state_root", fut=drop) is True
    assert drop.done() is True
    assert keep.done() is False
    assert hub.armed_count == 1
    assert hub.get("peer-1", kind="state_root") is not None


def test_state_root_lag_below_expected_fulfills() -> None:
    hub = SyncSolicitHub(
        verify_state_root=lambda *_a, **_k: "bad_state_root_response_height"
    )
    fut = _Fut()
    hub.arm(
        "peer-1",
        (MSG_STATE_ROOT_RESPONSE,),
        fut,
        {
            "kind": "state_root",
            "height": 10,
            "expected_head": "",
            "expected_state_root": "aa" * 32,
        },
    )
    msg = {
        "type": MSG_STATE_ROOT_RESPONSE,
        "data": {"height": 9, "state_root": "bb" * 32, "head_hash": "cc" * 32},
    }
    strikes: list[str] = []
    r = hub.fulfill_or_reject(
        _Peer(),
        MSG_STATE_ROOT_RESPONSE,
        msg["data"],
        msg,
        strike=lambda p, reason: strikes.append(reason) or False,
    )
    assert r.consumed is True
    assert r.detail == "state_root_lag"
    assert fut.result is msg
    assert strikes == []


def test_state_root_height_inflation_still_struck() -> None:
    hub = SyncSolicitHub(
        verify_state_root=lambda *_a, **_k: "bad_state_root_response_height"
    )
    fut = _Fut()
    hub.arm(
        "peer-1",
        (MSG_STATE_ROOT_RESPONSE,),
        fut,
        {"kind": "state_root", "height": 10, "expected_head": ""},
    )
    msg = {
        "type": MSG_STATE_ROOT_RESPONSE,
        "data": {"height": 11, "state_root": "aa" * 32},
    }
    strikes: list[str] = []
    r = hub.fulfill_or_reject(
        _Peer(),
        MSG_STATE_ROOT_RESPONSE,
        msg["data"],
        msg,
        strike=lambda p, reason: strikes.append(reason) or False,
    )
    assert r.consumed is True
    assert r.detail == "bad_state_root_response_height"
    assert fut.result is None
    assert strikes == ["bad_state_root_response_height"]


def test_state_root_and_mempool_waiters_concurrent() -> None:
    hub = SyncSolicitHub(verify_state_root=lambda *_a, **_k: None)
    mem_fut = _Fut()
    root_fut = _Fut()
    hub.arm("peer-1", (MSG_MEMPOOL,), mem_fut, {"kind": "mempool"})
    hub.arm(
        "peer-1",
        (MSG_STATE_ROOT_RESPONSE,),
        root_fut,
        {"kind": "state_root", "height": 1, "expected_head": ""},
    )
    assert hub.armed_count == 2
    root_msg = {
        "type": MSG_STATE_ROOT_RESPONSE,
        "data": {"height": 1, "state_root": "aa" * 32},
    }
    r_root = hub.fulfill_or_reject(
        _Peer(),
        MSG_STATE_ROOT_RESPONSE,
        root_msg["data"],
        root_msg,
        strike=lambda *_a: False,
    )
    assert r_root.consumed is True
    assert root_fut.result is root_msg
    assert mem_fut.result is None
    mem_msg = {"type": MSG_MEMPOOL, "data": [{"hash": "x"}]}
    r_mem = hub.fulfill_or_reject(
        _Peer(),
        MSG_MEMPOOL,
        mem_msg["data"],
        mem_msg,
        strike=lambda *_a: False,
    )
    assert r_mem.consumed is True
    assert mem_fut.result is mem_msg
    hub.clear("peer-1", kind="state_root")
    hub.clear("peer-1", kind="mempool")
    assert hub.armed_count == 0


def test_clear_state_root_kind_keeps_mempool() -> None:
    hub = SyncSolicitHub()
    hub.arm("peer-1", (MSG_MEMPOOL,), _Fut(), {"kind": "mempool"})
    hub.arm(
        "peer-1",
        (MSG_STATE_ROOT_RESPONSE,),
        _Fut(),
        {"kind": "state_root", "height": 1},
    )
    hub.clear("peer-1", kind="state_root")
    assert hub.mempool_solicit_armed("peer-1") is True
    assert hub.armed_count == 1


def test_fulfill_state_root_via_libp2p_peer_id() -> None:
    hub = SyncSolicitHub(verify_state_root=lambda *_a, **_k: None)
    fut = _Fut()
    rust_id = "12D3KooWtestpeer"
    hub.arm(
        rust_id,
        (MSG_STATE_ROOT_RESPONSE,),
        fut,
        {"kind": "state_root", "height": 1, "expected_head": ""},
    )
    peer = _Peer("docker-prod-mesh-2")
    peer._libp2p_peer_id = rust_id
    msg = {
        "type": MSG_STATE_ROOT_RESPONSE,
        "data": {"height": 1, "state_root": "aa" * 32},
    }
    r = hub.fulfill_or_reject(
        peer,
        MSG_STATE_ROOT_RESPONSE,
        msg["data"],
        msg,
        strike=lambda *_a: False,
    )
    assert r.consumed is True
    assert fut.result is msg


def test_no_network_import_in_solicit_domain() -> None:
    src = (ROOT / "sync" / "solicit.py").read_text(encoding="utf-8")
    assert "import network" not in src
    assert "from network" not in src
