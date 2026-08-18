#!/usr/bin/env python3
"""Fail-loud honesty for prod-critical silent-except surfaces."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from blockchain.immutable_state import ImmutableStateManager
from sync.sync_engine import SyncEngine


def test_sync_state_logs_wire_probe_failure(capsys):
    peer = SimpleNamespace(peer_id="peer1", height=1)
    node = SimpleNamespace(
        blockchain=SimpleNamespace(
            get_state_root=lambda: "abc",
            get_height=lambda: 1,
            get_block=lambda _h: None,
        ),
        request_peer_state_roots_sync=MagicMock(side_effect=RuntimeError("boom")),
        p2p=SimpleNamespace(_state_consistent=True),
    )
    # SyncEngine expects node with peers collector
    eng = SyncEngine(node)
    eng._collect_p2p_peers = lambda: [peer]  # type: ignore
    ok = eng.sync_state()
    captured = capsys.readouterr()
    assert "wire probe failed" in captured.out
    assert eng.get_status().get("wire_probe_ok") is False
    assert eng.get_status().get("wire_probe_probed") is True
    assert ok is False
    assert node.p2p._state_consistent is False


def test_empty_probe_does_not_wipe_last_known_green():
    """Block-gossip empty RTT must not LOCKED_DOWN a just-proven same-height match."""
    root = "aa" * 32
    peer = SimpleNamespace(peer_id="p1", height=1, head=root, dial_target="")
    node = SimpleNamespace(
        blockchain=SimpleNamespace(
            get_state_root=lambda: root,
            get_height=lambda: 1,
            get_block=lambda _h: None,
        ),
        request_peer_state_roots_sync=MagicMock(
            return_value=[{"peer_id": "p1", "height": 1, "state_root": root}]
        ),
        p2p=SimpleNamespace(_state_consistent=False),
        _state_consistent=False,
    )
    eng = SyncEngine(node)
    eng._collect_p2p_peers = lambda: [peer]  # type: ignore
    assert eng.sync_state() is True
    node.request_peer_state_roots_sync = MagicMock(return_value=[])
    assert eng.sync_state() is True
    assert eng.consistency.snapshot().consistent is True
    assert node._state_consistent is True


def test_sync_state_solo_keeps_never_probed():
    """Solo / no peers must leave wire_probe as never-probed and clear consistency."""
    node = SimpleNamespace(
        blockchain=SimpleNamespace(
            get_state_root=lambda: "abc",
            get_height=lambda: 1,
            get_block=lambda _h: None,
        ),
        p2p=SimpleNamespace(_state_consistent=True),
    )
    eng = SyncEngine(node)
    eng._collect_p2p_peers = lambda: []  # type: ignore
    ok = eng.sync_state()
    assert ok is False
    assert eng._last_wire_probe_ok is None
    assert node.p2p._state_consistent is False
    st = eng.get_status()
    assert st.get("wire_probe_probed") is False
    assert st.get("wire_probe_ok") is False


def test_sync_state_peers_behind_no_same_height_match_fail_closed(capsys):
    """Peers all behind (or empty same-height roots) must not paint green."""
    peer = SimpleNamespace(peer_id="peer1", height=0)
    node = SimpleNamespace(
        blockchain=SimpleNamespace(
            get_state_root=lambda: "abc",
            get_height=lambda: 5,
            get_block=lambda _h: None,
        ),
        request_peer_state_roots_sync=MagicMock(
            return_value=[{"peer_id": "peer1", "height": 3, "state_root": "abc"}]
        ),
        p2p=SimpleNamespace(_state_consistent=True),
    )
    eng = SyncEngine(node)
    eng._collect_p2p_peers = lambda: [peer]  # type: ignore
    ok = eng.sync_state()
    captured = capsys.readouterr()
    assert ok is False
    assert "same-height" in captured.out.lower()
    assert node.p2p._state_consistent is False


def test_sync_state_empty_probe_with_peers_fail_closed(capsys):
    peer = SimpleNamespace(peer_id="peer1", height=1)
    node = SimpleNamespace(
        blockchain=SimpleNamespace(
            get_state_root=lambda: "abc",
            get_height=lambda: 1,
            get_block=lambda _h: None,
        ),
        request_peer_state_roots_sync=MagicMock(return_value=[]),
        p2p=SimpleNamespace(_state_consistent=True),
    )
    eng = SyncEngine(node)
    eng._collect_p2p_peers = lambda: [peer]  # type: ignore
    ok = eng.sync_state()
    captured = capsys.readouterr()
    assert "empty" in captured.out.lower()
    assert ok is False
    assert eng.get_status().get("wire_probe_ok") is False
    assert node.p2p._state_consistent is False
    # Second tick must not storm another RTT (live miner HOL / prune).
    node.request_peer_state_roots_sync.reset_mock()
    ok2 = eng.sync_state()
    captured2 = capsys.readouterr()
    assert ok2 is False
    assert "backoff" in captured2.out.lower()
    node.request_peer_state_roots_sync.assert_not_called()


def test_empty_probe_sticky_green_expires(capsys):
    """Persistent empty wire must not stay green after consecutive empties."""
    root = "aa" * 32
    peer = SimpleNamespace(peer_id="p1", height=1, head=root, dial_target="")
    node = SimpleNamespace(
        blockchain=SimpleNamespace(
            get_state_root=lambda: root,
            get_height=lambda: 1,
            get_block=lambda _h: None,
        ),
        request_peer_state_roots_sync=MagicMock(
            return_value=[{"peer_id": "p1", "height": 1, "state_root": root}]
        ),
        p2p=SimpleNamespace(_state_consistent=False),
        _state_consistent=False,
    )
    eng = SyncEngine(node)
    eng._collect_p2p_peers = lambda: [peer]  # type: ignore
    eng._wire_probe_backoff_sec = 0.0
    eng._wire_sticky_empty_max = 3
    assert eng.sync_state() is True
    node.request_peer_state_roots_sync = MagicMock(return_value=[])
    assert eng.sync_state() is True
    assert eng.sync_state() is True
    assert eng.sync_state() is False
    captured = capsys.readouterr()
    assert "sticky green expired" in captured.out
    assert node._state_consistent is False


def test_sync_state_timeout_none_fail_closed(capsys):
    peer = SimpleNamespace(peer_id="peer1", height=1)
    node = SimpleNamespace(
        blockchain=SimpleNamespace(
            get_state_root=lambda: "abc",
            get_height=lambda: 1,
            get_block=lambda _h: None,
        ),
        request_peer_state_roots_sync=MagicMock(return_value=None),
        p2p=SimpleNamespace(_state_consistent=True),
    )
    eng = SyncEngine(node)
    eng._collect_p2p_peers = lambda: [peer]  # type: ignore
    ok = eng.sync_state()
    assert ok is False
    assert eng.get_status().get("wire_probe_ok") is False


def test_sync_status_unknown_probe_is_fail_closed():
    eng = SyncEngine(SimpleNamespace(p2p=SimpleNamespace(_state_consistent=True)))
    eng._collect_p2p_peers = lambda: []  # type: ignore
    st = eng.get_status()
    assert st.get("wire_probe_ok") is False
    assert st.get("wire_probe_probed") is False


def test_sync_state_missing_get_state_root_fail_closed(capsys):
    node = SimpleNamespace(
        blockchain=SimpleNamespace(get_height=lambda: 1),
        p2p=SimpleNamespace(_state_consistent=True),
    )
    eng = SyncEngine(node)
    eng._collect_p2p_peers = lambda: []  # type: ignore
    ok = eng.sync_state()
    captured = capsys.readouterr()
    assert ok is False
    assert "missing get_state_root" in captured.out
    assert node.p2p._state_consistent is False
    assert eng.get_status().get("wire_probe_ok") is False


def test_ims_reconcile_fail_loud_nonce():
    store = SimpleNamespace(
        get_balance_satoshi=lambda _a: 1_000_000,
        get_nonce=MagicMock(side_effect=RuntimeError("nonce down")),
    )
    ims = ImmutableStateManager()
    raised = False
    try:
        ims.reconcile_from_store(store, ["alice"], fail_loud=True)
    except RuntimeError:
        raised = True
    assert raised


def test_ims_reconcile_nonce_soft_without_fail_loud(capsys):
    store = SimpleNamespace(
        get_balance_satoshi=lambda _a: 2_000_000,
        get_nonce=MagicMock(side_effect=RuntimeError("nonce down")),
    )
    ims = ImmutableStateManager()
    n = ims.reconcile_from_store(store, ["bob"], fail_loud=False)
    assert n == 1
    assert ims.get_balance_satoshi("bob") == 2_000_000
    assert "get_nonce failed" in capsys.readouterr().out


def test_state_root_status_peer_probe_error_surface():
    # Static contract: api/http.py must expose peer_probe_error key
    from pathlib import Path

    text = Path("api/http.py").read_text(encoding="utf-8")
    assert "peer_probe_error" in text
    assert "record_state_root_mismatch failed" in Path("core/blockchain.py").read_text(
        encoding="utf-8"
    )
    assert "genesis meta write failed" in Path("core/blockchain.py").read_text(encoding="utf-8")
    bc_py = Path("core/blockchain.py").read_text(encoding="utf-8")
    assert "bind_tip_encoding_config failed" in bc_py
    assert "self.storage.set_balance(addr, float(amount))" not in bc_py
    assert "self.storage.set_balance(addr, int(amount))" in bc_py
    assert "parse_rpc_value_abs" in bc_py
    assert "UoW abort failed" in bc_py
    assert "canonical persist failed" in bc_py
    p2p_py = Path("network/p2p_node.py").read_text(encoding="utf-8")
    assert "parse_p2p_wire_abs" in p2p_py
    assert "fee_unparseable" in p2p_py
    assert "mempool has_transaction check failed" in p2p_py
    assert "native fe_quorum_reached failed" in Path("finality_engine.py").read_text(
        encoding="utf-8"
    )
    assert '_native_fb("ffg_accumulate_vote"' in Path(
        "consensus/finality_casper.py"
    ).read_text(encoding="utf-8")
    assert "total_active_stake failed; engine fallback" in Path(
        "consensus/adapter.py"
    ).read_text(encoding="utf-8")
    main_py = Path("main.py").read_text(encoding="utf-8")
    assert "self.db.set_balance(addr, float(amount))" not in main_py
    assert "self.db.set_balance(addr, int(amount))" in main_py
    assert "Genesis allocation failed" in main_py
    assert "secret lookup failed for" in main_py
    assert "sync_state probe failed" in Path("main.py").read_text(encoding="utf-8")
    assert "peer heights from get_peers_info failed" in text
    assert "bridge_result_normalize_failed" in text
    from api.http import _bridge_http_result
    import inspect as _inspect

    assert "bool(result)" not in _inspect.getsource(_bridge_http_result)


def test_shared_sync_engine_and_unsolicited_state_root_honesty():
    from pathlib import Path

    main_py = Path("main.py").read_text(encoding="utf-8")
    assert "p2p.sync_engine = self.sync_engine" in main_py
    assert "shared with P2P" in main_py
    p2p_py = Path("network/p2p_node.py").read_text(encoding="utf-8")
    solicit_py = Path("sync/solicit.py").read_text(encoding="utf-8")
    # ADR 0003: solicit-only strike lives in SyncSolicitHub (evacuated from p2p).
    assert "unsolicited_state_root_response" in solicit_py
    assert "solicit_hub.fulfill_or_reject" in p2p_py
    sync_py = Path("sync/sync_engine.py").read_text(encoding="utf-8")
    assert "State root mismatch vs" in sync_py
    http_py = Path("api/http.py").read_text(encoding="utf-8")
    assert 'after.get("state_consistent", False)' in http_py
    alerts = Path("deploy/prometheus/alerts.yml").read_text(encoding="utf-8")
    assert "AbsoluteSyncWireProbeNeverProbed" in alerts
    assert "AbsoluteProdSqliteEngine" in alerts


def test_bridge_http_result_normalize_failure_not_bool_object(monkeypatch):
    import api.http as http
    import bridge.adapter as adapter

    class _TruthyFail:
        success = False
        error = "locked"
        def __bool__(self):
            return True

    monkeypatch.setattr(
        adapter,
        "normalize_bridge_http_result",
        lambda _r: (_ for _ in ()).throw(RuntimeError("normalize down")),
    )
    out = http._bridge_http_result(_TruthyFail())
    assert out["success"] is False
    assert "locked" in str(out.get("error") or "")

    class _NoSuccess:
        def __bool__(self):
            return True

    out2 = http._bridge_http_result(_NoSuccess())
    assert out2["success"] is False
    assert out2.get("error") == "bridge_result_normalize_failed"


def test_bridge_for_request_prod_stats_fail_closed(monkeypatch):
    import api.http as http

    class _Cfg:
        deployment_mode = "prod"

    class _Bridge:
        _mode = "rust"

        def get_stats(self):
            raise RuntimeError("stats down")

    class _Handler:
        bridge = _Bridge()

    monkeypatch.setattr(http, "_is_production_cfg", lambda _c: True)
    assert http._bridge_for_request(_Handler, _Cfg()) is None


def test_local_needs_genesis_store_error_empty_tip_fail_closed(caplog):
    """Empty tip + store error must still request genesis, not skip as 'have chain'."""

    class _BoomStore:
        def get_height(self):
            return 0

        def get_last_block(self):
            raise RuntimeError("store down")

    eng = SyncEngine(SimpleNamespace(blockchain=_BoomStore()))
    with caplog.at_level(logging.WARNING, logger="Sync.Engine"):
        assert eng._local_needs_genesis() is True
    assert "get_last_block failed in _local_needs_genesis" in caplog.text


def test_local_needs_genesis_store_error_nonempty_does_not_force_genesis():
    """Non-empty height must not force genesis import over an existing chain."""

    class _BoomStore:
        def get_height(self):
            return 100

        def get_last_block(self):
            raise RuntimeError("store down")

    eng = SyncEngine(SimpleNamespace(blockchain=_BoomStore()))
    assert eng._local_needs_genesis() is False


def test_catchup_honesty_needles_present():
    from pathlib import Path

    assert "[EngineIO] needs_genesis checker failed" in Path(
        "sync/catchup/engine_io.py"
    ).read_text(encoding="utf-8")
    assert "[PathA] needs_genesis check failed" in Path(
        "sync/catchup/path_a.py"
    ).read_text(encoding="utf-8")
    assert "tip-safety shadow provider failed" in Path(
        "network/p2p_dispatch/tip_evidence.py"
    ).read_text(encoding="utf-8")


def test_registry_adapter_logs_bus_and_lockdown_failures(caplog):
    import logging
    from types import SimpleNamespace

    from consensus.bft.types import ConsensusSecurityEvidence
    from consensus.registry_adapter import (
        AdapterConsensusEvidence,
        AdapterConsensusLockdown,
        AdapterConsensusSideEffect,
    )

    class _Bus:
        def emit(self, *_a, **_k):
            raise RuntimeError("bus down")

    adapter = SimpleNamespace(bus=_Bus())

    def _bad_hook(_reason: str) -> None:
        raise RuntimeError("hook down")

    adapter._lockdown_hook = _bad_hook
    with caplog.at_level(logging.WARNING, logger="abs.consensus"):
        AdapterConsensusEvidence(adapter).emit(
            ConsensusSecurityEvidence(reason_code="double_vote", validator_id="v1")
        )
        AdapterConsensusLockdown(adapter).request_lockdown("consensus_double_sign")
        AdapterConsensusSideEffect(adapter).on_finalized("ab" * 32, 3)
    text = caplog.text
    assert "security.consensus_refuse emit failed" in text
    assert "security.consensus_lockdown emit failed" in text
    assert "consensus lockdown hook failed" in text
    assert "consensus.finalized emit failed" in text


def test_rocks_store_batch_open_assumes_open_on_probe_fail():
    from types import SimpleNamespace

    from storage.adapters.rocks_adapter import RocksDBStorageAdapter

    class _Boom:
        @property
        def in_transaction(self):
            raise RuntimeError("conn probe")

    store = SimpleNamespace(_pending_batch=None, _core=None, conn=_Boom())
    adapter = RocksDBStorageAdapter(store, repair_on_open=False)
    assert adapter._store_batch_open() is True


def test_silent_except_wave_needles():
    from pathlib import Path

    p2p = Path("network/p2p_node.py").read_text(encoding="utf-8")
    assert "native p2p_native_clamp_batch failed" in p2p
    assert "get_block failed during head-height bind" in p2p
    assert "set_peer_wire_codec failed" in p2p
    assert "set_timeout_ms failed" in p2p
    rocks = Path("storage/adapters/rocks_adapter.py").read_text(encoding="utf-8")
    assert "in_transaction probe failed; assume open batch" in rocks
    assert "storage ping failed" in rocks
    reg = Path("consensus/registry_adapter.py").read_text(encoding="utf-8")
    assert "security.consensus_refuse emit failed" in reg
    assert "except Exception:\n            pass" not in reg.replace("\r\n", "\n")
    peer_mgr = Path("network/peer_manager.py").read_text(encoding="utf-8")
    assert "[PeerManager] close failed" in peer_mgr
    catchup = Path("network/catchup_adapters.py").read_text(encoding="utf-8")
    assert "[CatchUpChain] head failed" in catchup
    fork = Path("network/fork_adapters.py").read_text(encoding="utf-8")
    assert "async reorg_and_import failed" in fork
    libp2p = Path("network/transport/libp2p_adapter/adapter.py").read_text(
        encoding="utf-8"
    )
    assert "attach_native failed" in libp2p
    assert "node close failed" in libp2p
    p2p = Path("network/p2p_node.py").read_text(encoding="utf-8")
    assert "def _try_local_head" in p2p
    assert "local_tip_unreadable" in p2p
    assert "coalesced wire probe task failed" in p2p
    assert "P2PLineFramer construct failed" in p2p
    assert "native capability probe failed: %s" in p2p
    handler = Path("network/p2p/message_handler.py").read_text(encoding="utf-8")
    assert "send_message failed" in handler or "%s failed peer=" in handler
    main = Path("main.py").read_text(encoding="utf-8")
    assert "set_accepting_requests failed at boot" in main
    db_py = Path("storage/database.py").read_text(encoding="utf-8")
    assert "BlockchainDB.__del__ close failed" in db_py
    persist = Path("storage/persistent_storage.py").read_text(encoding="utf-8")
    assert "PersistentStorage.__del__ close failed" in persist
    rocks_store = Path("storage/rocks_store.py").read_text(encoding="utf-8")
    assert "native engine drop failed" in rocks_store
    assert "corrupt live_state_root_height meta" in rocks_store
    assert "get_account_rows failed, per-account load" in rocks_store
    assert "except Exception:\n            height = -1" not in rocks_store.replace(
        "\r\n", "\n"
    )
    shadow = Path("consensus/tip_safety/shadow.py").read_text(encoding="utf-8")
    assert "get_height parse failed" in shadow
    assert "get_height failed: %s" in shadow


def test_blockchain_db_del_logs_close_failure(caplog):
    from storage.database import BlockchainDB

    db = BlockchainDB.__new__(BlockchainDB)

    def _boom() -> None:
        raise OSError("close boom")

    db.close = _boom  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="Database"):
        BlockchainDB.__del__(db)
    assert "BlockchainDB.__del__ close failed" in caplog.text
    assert "close boom" in caplog.text


def test_persistent_storage_del_logs_close_failure(caplog):
    from storage.persistent_storage import PersistentStorage

    store = PersistentStorage.__new__(PersistentStorage)

    def _boom() -> None:
        raise OSError("persist close boom")

    store.close = _boom  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="PersistentStorage"):
        PersistentStorage.__del__(store)
    assert "PersistentStorage.__del__ close failed" in caplog.text
    assert "persist close boom" in caplog.text


def test_catchup_head_failure_is_logged(caplog):
    from network.catchup_adapters import CatchUpP2PChainAdapter

    class _P2P:
        def head(self):
            raise RuntimeError("head boom")

    with caplog.at_level(logging.WARNING, logger="P2P.CatchUpAdapter"):
        assert CatchUpP2PChainAdapter(_P2P()).head() == ""
    assert "head failed" in caplog.text
    assert "head boom" in caplog.text


def test_fork_async_reorg_logs_then_sync_fallback(caplog):
    from network.fork_adapters import ForkReconcileP2PChainAdapter

    class _Loop:
        def is_running(self):
            return True

    class _P2P:
        def _reorg_and_import_async(self, *_a, **_k):
            raise RuntimeError("async boom")

        def _reorg_and_import(self, *_a, **_k):
            return True

    with caplog.at_level(logging.WARNING, logger="P2P.ForkAdapter"):
        ok = ForkReconcileP2PChainAdapter(_P2P(), _Loop()).reorg_and_import(
            1, {"hash": "aa"}
        )
    assert ok is True
    assert "async reorg_and_import failed" in caplog.text


def test_http_engine_result_refuses_truthy_objects():
    from api.http import _http_engine_result

    class _Truthy:
        def __bool__(self):
            return True

    assert _http_engine_result(True) == {"success": True}
    assert _http_engine_result(False) == {"success": False}
    assert _http_engine_result(None)["error"] == "engine_returned_none"
    assert _http_engine_result(_Truthy())["success"] is False
    assert _http_engine_result(_Truthy())["error"] == "engine_result_not_boolean"
    assert _http_engine_result({"ok": 1})["ok"] == 1
    flagged = type("R", (), {"success": False, "error": "locked"})()
    out = _http_engine_result(flagged)
    assert out["success"] is False
    assert out["error"] == "locked"


def test_format_tx_uses_satoshi_not_ieee_float():
    from api.eth_format import format_tx
    from runtime.amount import WEI_PER_SATOSHI, to_satoshi

    row = format_tx({"hash": "0xab", "value": 1.5, "block_height": 3})
    assert row["value"] == hex(to_satoshi(1.5) * WEI_PER_SATOSHI)
    junk = format_tx({"hash": "0xcd", "value": True})
    assert junk["value"] is None


def test_message_handler_import_refuses_truthy_non_bool():
    from network.p2p.message_handler import MessageHandler

    class _Chain:
        def add_block(self, _block):
            return object()

    h = MessageHandler(None, None, None, _Chain(), None)
    assert h._import_block({"hash": "x"}) is False

    class _Ok:
        def add_block(self, _block):
            return True

    assert MessageHandler(None, None, None, _Ok(), None)._import_block({"hash": "x"}) is True

