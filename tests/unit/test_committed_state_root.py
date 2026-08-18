"""Committed state_root must be O(1) for HTTP / P2P / harness (48h soak)."""

from types import SimpleNamespace

from core.blockchain import Blockchain


def test_get_state_root_uses_live_meta_without_recompute():
    bc = Blockchain.__new__(Blockchain)
    bc.storage = SimpleNamespace(
        get_live_state_root_meta=lambda: ("ab" * 32, 42),
        get_last_block=lambda: (_ for _ in ()).throw(AssertionError("last_block")),
    )

    def _boom() -> str:
        raise AssertionError("must not recompute committed root")

    bc._compute_state_root_from_db = _boom  # type: ignore[method-assign]
    assert bc.get_state_root() == "ab" * 32


def test_get_state_root_falls_back_to_tip_header():
    bc = Blockchain.__new__(Blockchain)
    bc.storage = SimpleNamespace(
        get_last_block=lambda: {"height": 3, "state_root": "cd" * 32},
    )
    called = {"n": 0}

    def _compute() -> str:
        called["n"] += 1
        return "ef" * 32

    bc._compute_state_root_from_db = _compute  # type: ignore[method-assign]
    assert bc.get_state_root() == "cd" * 32
    assert called["n"] == 0


def test_get_state_root_empty_when_cache_missing():
    bc = Blockchain.__new__(Blockchain)
    bc.storage = SimpleNamespace(
        get_live_state_root_meta=lambda: ("", -1),
        get_last_block=lambda: {"height": 0, "state_root": ""},
    )

    def _boom() -> str:
        raise AssertionError("HTTP/P2P get_state_root must not rescan accounts")

    bc._compute_state_root_from_db = _boom  # type: ignore[method-assign]
    assert bc.get_state_root() == ""
