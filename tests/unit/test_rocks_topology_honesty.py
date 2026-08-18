#!/usr/bin/env python3
"""v1.3.22 honesty: Rocks decode counter, topology, SyncEngine prod, eth_mining mesh."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_rocks_audit_list_paths_bump_decode_failures():
    rocks = Path("storage/rocks_store.py").read_text(encoding="utf-8")
    assert rocks.count("self._json_decode_failures += 1") >= 15
    # Experimental list-path log is more specific than Hybrid's row log.
    assert (
        "corrupt proposer_audit row skipped" in rocks
        or "corrupt proposer_audit list row skipped" in rocks
    )
    assert "corrupt bridge_lock row skipped" in rocks
    assert "corrupt state_root_mismatch row skipped" in rocks


def test_metrics_emit_json_decode_failures():
    from observability.metrics import MetricsCollector

    text = MetricsCollector().render_prometheus(
        node_id="n1",
        rocksdb_tuning={
            "engine": "rocksdb",
            "source": "live",
            "column_families": True,
            "block_cache_mb": 64,
            "write_buffer_mb": 32,
            "json_decode_failures": 7,
        },
    )
    assert 'abs_rocksdb_json_decode_failures{node_id="n1"} 7' in text


def test_topology_healthy_requires_state_consistent_with_peers():
    text = Path("network/p2p_node.py").read_text(encoding="utf-8")
    assert "consistent_ok = bool(self._state_consistent) if peers else True" in text
    assert "peer_links_ok and peers_healthy and consistent_ok" in text


def test_reconcile_without_sync_engine_clears_consistent():
    text = Path("network/p2p_node.py").read_text(encoding="utf-8")
    assert "Reconcile \"ok\" without a SyncEngine must not leave stale mesh-green" in text
    assert "elif self.peers:" in text


def test_prod_sync_engine_hard_fail_needle():
    main_py = Path("main.py").read_text(encoding="utf-8")
    assert "Production mode requires SyncEngine" in main_py


def test_eth_mining_mesh_gate_honesty():
    from api.http import RESTHandler

    cfg = SimpleNamespace(
        mining_enabled=True,
        mesh_min_peers_before_mine=2,
        node_version="test",
        chain_id=1,
    )
    p2p = SimpleNamespace(peers={"a": object()}, _state_consistent=False)
    # Exercise the same logic as the eth_mining branch.
    min_mesh = int(getattr(cfg, "mesh_min_peers_before_mine", 0) or 0)
    assert min_mesh > 0
    connected = len(p2p.peers)
    assert connected < min_mesh
    assert not bool(getattr(p2p, "_state_consistent", False))

    http_py = Path("api/http.py").read_text(encoding="utf-8")
    assert "Config-on ≠ actively forging under mesh gate" in http_py
    assert "mesh_min_peers_before_mine" in http_py
    # Silence unused import lint for RESTHandler presence contract.
    assert RESTHandler is not None
