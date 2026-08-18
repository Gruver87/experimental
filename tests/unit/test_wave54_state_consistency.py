"""Wave 54 — state consistency harness API."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
from wave_expect import EXPECTED_API_WAVE


class _FakeP2P:
    def __init__(self, peer_roots=None, consistent=True):
        self._peer_roots = peer_roots or []
        self._state_consistent = consistent

    def request_peer_state_roots_sync(self, timeout=8):
        return self._peer_roots


class _FakeBC:
    def __init__(self, height=5, live="0xlive", tip="0xlive"):
        self._height = height
        self._live = live
        self._tip = tip

    def get_height(self):
        return self._height

    def get_state_root(self):
        return self._live

    def get_last_block(self):
        return {"height": self._height, "state_root": self._tip, "hash": "0xabc"}

    def get_block(self, h):
        return None

    def get_state_root_policy(self):
        from runtime.state_root_encoding import state_root_encoding_status

        return {
            "baseline_height": self._height,
            "verify_peer_state_root": True,
            "encoding": state_root_encoding_status(),
        }


class _FakeDB:
    def get_state_root_mismatches(self, limit=20):
        return []

    def get_stats(self):
        return {"total_accounts": 1, "total_transactions": 1}

    def get_all_accounts(self):
        return [{"address": "0x1", "balance": 100.0, "nonce": 0}]

    def get_total_supply(self):
        return 1_000_000.0


class _FakeCfg:
    node_id = "test-node"
    chain_id = 77777
    max_supply = 221_000_000


def test_harness_healthy_aligned():
    from api.http import _build_state_consistency_harness

    root = "a" * 64
    p2p = _FakeP2P([{"peer_id": "p2", "height": 5, "state_root": root}])
    h = _build_state_consistency_harness(
        p2p, _FakeBC(live=root, tip=root), _FakeCfg(), _FakeDB()
    )
    assert h["harness_healthy"] is True
    assert h["tip_state_aligned"] is True
    assert h["canonical_state_root_source"] == "blockchain.database"
    assert h["api_wave"] == EXPECTED_API_WAVE
    assert h["failed_checks"] == []


def test_harness_fails_tip_drift():
    from api.http import _build_state_consistency_harness

    p2p = _FakeP2P()
    h = _build_state_consistency_harness(
        p2p,
        _FakeBC(live="b" * 64, tip="a" * 64),
        _FakeCfg(),
        _FakeDB(),
    )
    assert h["harness_healthy"] is False
    assert "tip_state_aligned" in h["failed_checks"]


def test_harness_fails_peer_root_mismatch():
    from api.http import _build_state_consistency_harness

    local = "c" * 64
    p2p = _FakeP2P([{"peer_id": "p2", "height": 5, "state_root": "d" * 64}])
    h = _build_state_consistency_harness(
        p2p, _FakeBC(live=local, tip=local), _FakeCfg(), _FakeDB()
    )
    assert h["harness_healthy"] is False
    assert "peer_state_roots" in h["failed_checks"]


def test_harness_quick_mode_metadata():
    from api.http import _build_state_consistency_harness

    root = "e" * 64
    p2p = _FakeP2P([{"peer_id": "p2", "height": 5, "state_root": root}])
    h = _build_state_consistency_harness(
        p2p, _FakeBC(live=root, tip=root), _FakeCfg(), _FakeDB(),
        peer_timeout=3.0, quick=True,
    )
    assert h["monitor_quick"] is True
    assert h["peer_timeout_sec"] == 3.0
    assert h["harness_healthy"] is True


def test_harness_same_chain_lag_passes_and_flag_lag_ok():
    """Peer at h-1 with matching historical root is same-chain, not a fork.

    Sticky _state_consistent=False must not fail the harness when this probe
    already matched wire roots (5h STRICT soak false-negative).
    """
    from api.http import _build_state_consistency_harness

    live = "f" * 64
    hist = "a" * 64

    class _LagBC(_FakeBC):
        def __init__(self):
            super().__init__(height=6, live=live, tip=live)

        def get_block(self, h):
            if int(h) == 5:
                return {"height": 5, "state_root": hist, "hash": "0x5"}
            return None

    p2p = _FakeP2P(
        [{"peer_id": "p2", "height": 5, "state_root": hist}],
        consistent=False,
    )
    h = _build_state_consistency_harness(p2p, _LagBC(), _FakeCfg(), _FakeDB())
    assert "peer_state_roots" not in h["failed_checks"]
    assert "peer_probe_ok" not in h["failed_checks"]
    assert "p2p_state_consistent" not in h["failed_checks"]
    assert h["harness_healthy"] is True


def test_harness_empty_wire_with_peers_fails():
    from api.http import _build_state_consistency_harness

    class _ConnectedEmpty(_FakeP2P):
        def peer_count(self):
            return 2

    root = "e" * 64
    h = _build_state_consistency_harness(
        _ConnectedEmpty([]),
        _FakeBC(live=root, tip=root),
        _FakeCfg(),
        _FakeDB(),
    )
    assert h["harness_healthy"] is False
    assert h["peer_probe_error"] == "empty"
    assert "peer_probe_ok" in h["failed_checks"]


def test_harness_empty_wire_without_peers_ok():
    from api.http import _build_state_consistency_harness

    root = "e" * 64
    h = _build_state_consistency_harness(
        _FakeP2P([]),
        _FakeBC(live=root, tip=root),
        _FakeCfg(),
        _FakeDB(),
    )
    assert h["peer_probe_error"] is None
    assert "peer_probe_ok" not in h["failed_checks"]


def test_harness_lag_still_fails_historical_mismatch():
    from api.http import _build_state_consistency_harness

    live = "f" * 64

    class _LagBC(_FakeBC):
        def __init__(self):
            super().__init__(height=6, live=live, tip=live)

        def get_block(self, h):
            if int(h) == 5:
                return {"height": 5, "state_root": "a" * 64, "hash": "0x5"}
            return None

    p2p = _FakeP2P(
        [{"peer_id": "p2", "height": 5, "state_root": "b" * 64}],
        consistent=True,
    )
    h = _build_state_consistency_harness(p2p, _LagBC(), _FakeCfg(), _FakeDB())
    assert h["harness_healthy"] is False
    assert "peer_state_roots" in h["failed_checks"]


def test_harness_empty_roots_at_height_fail():
    from api.http import _build_state_consistency_harness

    p2p = _FakeP2P()
    h = _build_state_consistency_harness(
        p2p, _FakeBC(height=5, live="", tip=""), _FakeCfg(), _FakeDB()
    )
    assert h["harness_healthy"] is False
    assert "tip_state_aligned" in h["failed_checks"]


def test_harness_tip_drift_not_painted_by_peer_roots():
    from api.http import _build_state_consistency_harness

    live = "b" * 64
    p2p = _FakeP2P([{"peer_id": "p2", "height": 5, "state_root": live}])
    h = _build_state_consistency_harness(
        p2p, _FakeBC(live=live, tip="a" * 64), _FakeCfg(), _FakeDB()
    )
    assert h["tip_metadata_drift"] is True
    assert h["harness_healthy"] is False
    assert "tip_state_aligned" in h["failed_checks"]
