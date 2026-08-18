"""Coalesce concurrent state_root probes; HTTP timeout must not cancel inflight."""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from network.p2p_node import P2PNode


def _coalesce_node(*, peers=None):
    node = object.__new__(P2PNode)
    node._state_root_probe_task = None
    node._state_root_probe_lock = None
    node._wire_probe_hold_until = 0.0
    node.apply_queue = None
    live = {"p": object()} if peers is None else dict(peers)
    node.peer_manager = SimpleNamespace(peers=live)
    return node


def test_solicit_height_uses_local_tip_not_stale_peer_height():
    node = object.__new__(P2PNode)
    node.blockchain = SimpleNamespace(get_height=lambda: 10)
    assert node._state_root_solicit_height(SimpleNamespace(height=9)) == 10
    assert node._state_root_solicit_height(SimpleNamespace(height=9), 10) == 10
    assert node._state_root_solicit_height(SimpleNamespace(height=10), 10) == 10
    assert node._state_root_solicit_height(SimpleNamespace(height=0), 10) == 10
    assert node._state_root_solicit_height(SimpleNamespace(height=12), 10) == 10


@pytest.mark.asyncio
async def test_coalesced_peer_state_roots_joins_inflight():
    node = _coalesce_node()
    calls = []

    async def _roots(*, per_peer_timeout=8.0, retry=True):
        calls.append((per_peer_timeout, retry))
        await asyncio.sleep(0.05)
        return [{"peer_id": "p", "height": 1, "state_root": "aa"}]

    node.request_peer_state_roots = _roots  # type: ignore[method-assign]
    t1 = asyncio.create_task(node._coalesced_peer_state_roots())
    t2 = asyncio.create_task(node._coalesced_peer_state_roots())
    r1, r2 = await asyncio.gather(t1, t2)
    assert r1 == r2
    assert len(calls) == 1
    assert calls[0] == (6.5, False)


def test_stash_late_state_root_only_after_recent_timeout():
    node = object.__new__(P2PNode)
    node._state_root_late = {}
    node._state_root_timeout_at = {}
    node._state_root_late_accepts_total = 0
    peer = SimpleNamespace(peer_id="p")
    payload = {"height": 1, "state_root": "aa" * 32}
    assert node._stash_late_state_root(peer, payload) is False
    node._state_root_timeout_at["p"] = time.monotonic()
    assert node._stash_late_state_root(peer, payload) is True
    assert node._state_root_late["p"][0]["height"] == 1
    assert node._state_root_late_accepts_total == 1


def test_sync_waiter_timeout_does_not_cancel_inflight():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    node = _coalesce_node()
    node._loop = loop
    node._running = True
    finished = {"ok": False, "cancelled": False}

    async def _slow_roots(*, per_peer_timeout=8.0, retry=True):
        try:
            await asyncio.sleep(1.2)
            finished["ok"] = True
            return [{"peer_id": "p"}]
        except asyncio.CancelledError:
            finished["cancelled"] = True
            raise

    node.request_peer_state_roots = _slow_roots  # type: ignore[method-assign]
    try:
        out = node.request_peer_state_roots_sync(timeout=0.5)
        assert out is None
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline and not finished["ok"]:
            time.sleep(0.05)
        assert finished["ok"] is True
        assert finished["cancelled"] is False
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_coalesce_empty_peers_does_not_join_stale_flight():
    """Isolated node must not wait on a dead-socket coalesced inflight."""
    node = _coalesce_node(peers={})
    started = asyncio.Event()

    async def _slow(*, per_peer_timeout=8.0, retry=True):
        started.set()
        await asyncio.sleep(5)
        return [{"peer_id": "dead"}]

    stale = asyncio.create_task(_slow())
    await started.wait()
    node._state_root_probe_task = stale
    t0 = time.monotonic()
    out = await asyncio.wait_for(node._coalesced_peer_state_roots(), timeout=0.5)
    assert out == []
    assert (time.monotonic() - t0) < 0.4
    stale.cancel()
    await asyncio.gather(stale, return_exceptions=True)


def test_sync_empty_peers_returns_empty_not_timeout():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    node = _coalesce_node(peers={})
    node._loop = loop
    node._running = True

    async def _must_not_run(*, per_peer_timeout=8.0, retry=True):
        raise AssertionError("isolated node must not start a state_root flight")

    node.request_peer_state_roots = _must_not_run  # type: ignore[method-assign]
    try:
        t0 = time.monotonic()
        out = node.request_peer_state_roots_sync(timeout=8)
        assert out == []
        assert (time.monotonic() - t0) < 0.5
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)


def test_consume_late_state_root_returns_stashed_payload():
    node = object.__new__(P2PNode)
    node._state_root_late = {}
    peer = SimpleNamespace(peer_id="p")
    assert node._consume_late_state_root(peer) is None
    payload = {"height": 3, "state_root": "ab" * 32}
    node._state_root_late["p"] = (payload, time.monotonic())
    got = node._consume_late_state_root(peer)
    assert got == payload
    assert node._consume_late_state_root(peer) is None


def test_apply_completed_wire_probe_sets_consistent() -> None:
    from sync.sync_engine import SyncEngine

    node = object.__new__(P2PNode)
    root = "aa" * 32
    node.blockchain = SimpleNamespace(
        get_state_root=lambda: root,
        get_height=lambda: 5,
    )
    node._state_consistent = False
    peer = SimpleNamespace(peer_id="p1", height=5, head=root, dial_target="")
    node.peer_manager = SimpleNamespace(peers={"p1": peer})
    eng = SyncEngine(node)
    eng._collect_p2p_peers = lambda: [peer]  # type: ignore
    node.sync_engine = eng
    assert eng.consistency.snapshot().consistent is False

    async def _done():
        return [{"peer_id": "p1", "height": 5, "state_root": root}]

    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(_done())
        loop.run_until_complete(task)
        node._apply_completed_wire_probe(task)
    finally:
        loop.close()
    assert eng.consistency.snapshot().consistent is True
    assert node._state_consistent is True


def test_apply_completed_wire_probe_logs_task_failure(caplog) -> None:
    import logging

    node = object.__new__(P2PNode)

    async def _boom():
        raise RuntimeError("probe boom")

    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(_boom())
        try:
            loop.run_until_complete(task)
        except RuntimeError:
            pass
        with caplog.at_level(logging.WARNING, logger="P2P"):
            node._apply_completed_wire_probe(task)
    finally:
        loop.close()
    assert "coalesced wire probe task failed" in caplog.text


@pytest.mark.asyncio
async def test_state_root_send_enqueues_without_waiting_write():
    from network.p2p_node import MSG_STATE_ROOT_REQUEST, PeerConnection

    peer = PeerConnection(send_queue_max=32, drain_timeout_sec=5.0)
    peer._ensure_send_worker = lambda: None  # type: ignore[method-assign]
    peer._send_wake = asyncio.Event()
    t0 = time.monotonic()
    ok = await asyncio.wait_for(
        peer.send(MSG_STATE_ROOT_REQUEST, {"height": 1}),
        timeout=0.5,
    )
    assert ok is True
    assert (time.monotonic() - t0) < 0.4
    item = peer._send_root_q.get_nowait()
    assert item[0] == MSG_STATE_ROOT_REQUEST
    assert item[1] == {"height": 1}


@pytest.mark.asyncio
async def test_request_peer_state_root_consumes_late_stash_without_retry():
    node = object.__new__(P2PNode)
    node.blockchain = SimpleNamespace(get_height=lambda: 1)
    peer = SimpleNamespace(peer_id="p", height=1)
    node._consume_late_state_root = lambda _p: {"height": 1, "state_root": "aa" * 32}
    node._state_root_request_ctx = lambda _h: {"kind": "state_root", "height": 1}
    called = {"wait": 0}

    async def _wait(*_a, **_k):
        called["wait"] += 1
        return None

    node._wait_peer_response = _wait  # type: ignore[method-assign]
    out = await node.request_peer_state_root(peer, 1, timeout=0.4, retry=False)
    assert out["height"] == 1
    assert out["state_root"] == "aa" * 32
    assert called["wait"] == 0


@pytest.mark.asyncio
async def test_request_peer_state_roots_drains_stash_after_empty_wait():
    node = object.__new__(P2PNode)
    peer = SimpleNamespace(peer_id="p1", height=4)
    node.blockchain = SimpleNamespace(get_height=lambda: 4)
    node.peer_manager = SimpleNamespace(peers={"p1": peer})

    async def _empty(*_a, **_k):
        return None

    node.request_peer_state_root = _empty  # type: ignore[method-assign]
    payload = {"height": 4, "state_root": "ab" * 32}
    node._consume_late_state_root = lambda _p: dict(payload)
    out = await node.request_peer_state_roots(per_peer_timeout=0.4, retry=False)
    assert len(out) == 1
    assert out[0]["peer_id"] == "p1"
    assert out[0]["height"] == 4


def test_late_state_root_stash_requires_recent_timeout():
    node = object.__new__(P2PNode)
    node._state_root_late = {}
    node._state_root_timeout_at = {"p": time.monotonic()}
    node._state_root_late_accepts_total = 0
    peer = SimpleNamespace(peer_id="p")
    payload = {"height": 4, "state_root": "aa" * 32}
    assert node._stash_late_state_root(peer, payload) is True
    assert node._state_root_late["p"][0]["height"] == 4
    assert node._state_root_late_accepts_total == 1


@pytest.mark.asyncio
async def test_wait_wire_probe_gate_holds_until():
    node = object.__new__(P2PNode)
    node.apply_queue = SimpleNamespace(busy=False)
    node._wire_probe_hold_until = time.monotonic() + 0.25
    waited = await node._wait_wire_probe_gate(1.0)
    assert waited >= 0.2
    assert waited < 0.7


@pytest.mark.asyncio
async def test_coalesced_waits_post_forge_hold_before_flight():
    node = _coalesce_node()
    node._wire_probe_hold_until = time.monotonic() + 0.2
    started = []

    async def _roots(*, per_peer_timeout=8.0, retry=True):
        started.append(time.monotonic())
        return [{"peer_id": "p", "height": 1, "state_root": "aa"}]

    node.request_peer_state_roots = _roots  # type: ignore[method-assign]
    t0 = time.monotonic()
    out = await node._coalesced_peer_state_roots()
    assert out[0]["peer_id"] == "p"
    assert started and (started[0] - t0) >= 0.15
