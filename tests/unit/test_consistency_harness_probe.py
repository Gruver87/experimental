"""State consistency harness peer_probe_error surface."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_harness_exposes_peer_probe_error():
    from api.http import _build_state_consistency_harness

    cfg = MagicMock()
    cfg.node_id = "n1"
    cfg.chain_id = 1
    cfg.max_supply = 221_000_000

    bc = MagicMock()
    bc.get_height.return_value = 5
    bc.get_state_root.return_value = "aa" * 32
    bc.get_last_block.return_value = {"state_root": "aa" * 32}
    bc.get_state_root_policy.return_value = {}

    p2p = MagicMock()
    p2p._state_consistent = True
    p2p.request_peer_state_roots_sync.side_effect = TimeoutError("peer wire timeout")

    db = MagicMock()
    db.get_state_root_mismatches.return_value = []
    db.get_cached_account_count.return_value = 1
    db.get_cached_total_supply.return_value = 100.0
    db.get_stats.side_effect = AssertionError("harness must not get_stats")
    db.get_all_accounts.side_effect = AssertionError("harness must not get_all_accounts")
    db.get_total_supply.side_effect = AssertionError("harness must not get_total_supply")

    harness = _build_state_consistency_harness(p2p, bc, cfg, db, quick=True)
    assert harness["peer_probe_error"]
    assert "peer wire timeout" in harness["peer_probe_error"]
    assert harness["harness_healthy"] is False


def test_harness_does_not_prefix_scan_on_http_path():
    from api.http import _build_state_consistency_harness

    cfg = MagicMock()
    cfg.node_id = "n1"
    cfg.chain_id = 1
    cfg.max_supply = 221_000_000

    bc = MagicMock()
    bc.get_height.return_value = 5
    bc.get_state_root.return_value = "aa" * 32
    bc.get_last_block.return_value = {"state_root": "aa" * 32}
    bc.get_state_root_policy.return_value = {
        "encoding": {"active": {"version": 2, "active": True, "satoshi_tip_ready": True}}
    }

    p2p = MagicMock()
    p2p._state_consistent = True
    p2p.request_peer_state_roots_sync.return_value = [
        {"peer_id": "p2", "height": 5, "state_root": "aa" * 32}
    ]

    db = MagicMock()
    db.get_state_root_mismatches.return_value = []
    db.get_cached_account_count.return_value = 4
    db.get_cached_total_supply.return_value = 100.0
    db.get_stats.side_effect = AssertionError("harness must not get_stats")
    db.get_all_accounts.side_effect = AssertionError("harness must not scan accounts")
    db.get_total_supply.side_effect = AssertionError("harness must not get_total_supply")

    harness = _build_state_consistency_harness(p2p, bc, cfg, db, quick=True)
    assert harness["account_count"] == 4
    assert harness["total_supply_abs"] == 100.0
    db.get_stats.assert_not_called()
    db.get_all_accounts.assert_not_called()
    db.get_total_supply.assert_not_called()
