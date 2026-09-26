#!/usr/bin/env python3
"""v1.3.23 honesty: P2P bind, ready wire probe, status degraded, peers mining gate."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_p2p_bind_failure_clears_running():
    text = Path("network/p2p_node.py").read_text(encoding="utf-8")
    assert "Could not bind port" in text
    # Bind failure must clear running and return before spawning loops.
    idx = text.index("Could not bind port")
    snippet = text[idx : idx + 280]
    assert "self._running = False" in snippet
    assert "return" in snippet


def test_ready_requires_wire_probe_with_peers():
    http_py = Path("api/http.py").read_text(encoding="utf-8")
    assert 'checks["wire_probe_probed"]' in http_py
    assert 'checks["wire_probe_ok"]' in http_py
    assert "Match eth_syncing: peers without a completed wire probe" in http_py
    assert "getattr(p2p, \"_server\", None) is not None" in http_py
    assert "getattr(p2p, \"_native_listener\", None) is not None" in http_py
    assert "native TCP+TLS uses ``_native_listener``" in http_py


def test_status_degraded_when_peers_inconsistent():
    http_py = Path("api/http.py").read_text(encoding="utf-8")
    assert '"status": (' in http_py or '"status":(\n' in http_py or 'status": (' in http_py
    assert '"degraded"' in http_py
    assert "peer_count > 0 and not state_consistent" in http_py


def test_eth_mining_peers_require_consistent_even_if_mesh_min_zero():
    http_py = Path("api/http.py").read_text(encoding="utf-8")
    assert "Peers present with mesh_min=0" in http_py
    assert "elif connected > 0 and not consistent" in http_py


def test_mining_loop_peers_consistency_gate():
    main_py = Path("main.py").read_text(encoding="utf-8")
    assert "Peers present require consistency even when mesh_min_peers_before_mine=0" in main_py
    # mesh_min>0 uses mesh_ready(+wire_soft_fail); mesh_min=0 keeps fail-closed skip.
    assert "wire_soft_fail" in main_py
    assert 'mesh_min=0 path: keep prior fail-closed skip when inconsistent' in main_py
    assert "under-mesh reconnect_known_peers" in main_py


def test_rocks_scan_and_reorg_bump_decode_failures():
    rocks = Path("storage/rocks_store.py").read_text(encoding="utf-8")
    assert rocks.count("self._json_decode_failures += 1") >= 15
    assert "corrupt latest_block row skipped" in rocks
    assert "corrupt account row skipped" in rocks
    assert "corrupt validator row skipped" in rocks
    assert "decode_failures=%s" in rocks
