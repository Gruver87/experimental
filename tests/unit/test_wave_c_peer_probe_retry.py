#!/usr/bin/env python3
"""Wave C: peer_probe harness retries once on timeout/empty."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.http import _build_state_consistency_harness


def test_peer_probe_retries_once_on_timeout() -> None:
    bc = MagicMock()
    bc.get_height.return_value = 10
    bc.get_state_root.return_value = "aa" * 32
    bc.get_last_block.return_value = {"state_root": "aa" * 32}
    p2p = MagicMock()
    p2p.peer_count.return_value = 2
    p2p._state_consistent = True
    p2p.request_peer_state_roots_sync.side_effect = [
        None,
        [{"peer_id": "p1", "height": 10, "state_root": "aa" * 32}],
    ]
    cfg = MagicMock()
    cfg.node_id = "n1"
    cfg.chain_id = 1
    out = _build_state_consistency_harness(p2p, bc, cfg, peer_timeout=1.0)
    assert out["peer_probe_error"] is None
    assert int(out["peer_probe_attempts"]) == 2
    assert p2p.request_peer_state_roots_sync.call_count == 2
    assert "peer_probe_ok" not in (out.get("failed_checks") or [])


def test_source_has_peer_probe_retry_needle() -> None:
    http = (ROOT / "api" / "http.py").read_text(encoding="utf-8")
    assert "peer_probe_attempts" in http
    assert "max_attempts = 2" in http
