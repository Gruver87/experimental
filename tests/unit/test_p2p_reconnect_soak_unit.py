# tests/unit/test_p2p_reconnect_soak_unit.py
"""Bounded reconnect ownership soak (unit): schedule_connect coalesces dials."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_schedule_connect_coalesces_inflight_dials():
    from network.p2p_node import P2PNode

    node = object.__new__(P2PNode)
    node._connect_tasks = {}
    calls = []

    async def _connect(host, port):
        calls.append((host, port))
        await asyncio.sleep(0.05)
        return True

    node.connect_peer = _connect  # type: ignore[method-assign]
    node._schedule_connect("127.0.0.1", 15001)
    node._schedule_connect("127.0.0.1", 15001)
    node._schedule_connect("127.0.0.1", 15001)
    await asyncio.sleep(0.1)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_bootstrap_retry_uses_schedule_connect(monkeypatch):
    from network import p2p_node as mod

    node = object.__new__(mod.P2PNode)
    node._running = True
    node.config = SimpleNamespace(bootstrap_peers=["10.0.0.2:15001"])
    node._bootstrap_redial_total = 0
    node._peer_connect_task_fail = 0
    node.peer_manager = SimpleNamespace(peers={})
    scheduled = []

    def _sched(host, port):
        scheduled.append(f"{host}:{port}")

    node._schedule_connect = _sched  # type: ignore[method-assign]
    node._missing_bootstrap_addrs = lambda: ["10.0.0.2:15001"]  # type: ignore

    async def _fast_sleep(_):
        node._running = False

    monkeypatch.setattr(mod.asyncio, "sleep", _fast_sleep)
    await node._bootstrap_retry_loop()
    assert scheduled == ["10.0.0.2:15001"]
    assert int(node._bootstrap_redial_total) == 1
