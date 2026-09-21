"""Industrial HIGH honesty: slash / demote-require / bridge emit / libp2p dial."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bridge.ports import InboundEnvelope, InboundStatus, ValidationResult
from bridge.validators import InboundMessageValidator
from consensus.registry_adapter import AdapterValidatorRegistry
from network.transport.errors import TransportCapabilityError
from network.transport.libp2p_adapter import Libp2pTransportAdapter
from network.transport.types import PeerEndpoint
from runtime.native_capabilities import NativeFamily, get_registry
from tests.unit.test_adr0021_phase2_store import _mk_tx


def test_mark_slashed_raises_when_both_backends_fail():
    class _Boom:
        def slash_validator(self, _vid):
            raise RuntimeError("adapter_slash_boom")

        validator_registry = SimpleNamespace(
            slash_validator=lambda _vid: (_ for _ in ()).throw(
                RuntimeError("registry_slash_boom")
            )
        )

    reg = AdapterValidatorRegistry(_Boom())
    with pytest.raises(RuntimeError, match="mark_slashed failed"):
        reg.mark_slashed("0xdead", "double_vote")


def test_mark_slashed_ok_via_adapter():
    seen = []

    class _Ok:
        def slash_validator(self, vid):
            seen.append(vid)

    reg = AdapterValidatorRegistry(_Ok())
    reg.mark_slashed("0xabc", "offline")
    assert seen == ["0xabc"]


def test_mempool_demote_refused_under_require():
    from blockchain.mempool import Mempool
    from runtime.native_capabilities import bootstrap_native_capabilities

    reg = get_registry()
    reg.reset_for_tests()
    try:
        bootstrap_native_capabilities()
        reg._mode = "require"
        reg._backends[NativeFamily.MEMPOOL_STORE] = "rust"

        pool = Mempool(max_size=16, min_fee=0.0)
        boom_store = SimpleNamespace(
            insert=lambda *_a, **_k: (_ for _ in ()).throw(
                RuntimeError("mempool_store_lock_poisoned")
            ),
            get_sorted=lambda *_a, **_k: [],
            size=lambda: 0,
            contains=lambda *_a, **_k: False,
        )
        pool._native_store = boom_store
        pool._store_backend = "rust"

        with pytest.raises(RuntimeError, match="forbids demote"):
            pool.add(_mk_tx("after", 5.0), signature_preverified=True)

        assert pool._native_store is boom_store
        assert pool._store_backend == "rust"
        assert pool._store_demoted is False
    finally:
        reg.reset_for_tests()
        bootstrap_native_capabilities()


def test_mempool_demote_allowed_in_auto():
    from blockchain.mempool import Mempool
    from runtime.native_capabilities import bootstrap_native_capabilities

    reg = get_registry()
    reg.reset_for_tests()
    try:
        bootstrap_native_capabilities()
        reg._mode = "auto"
        reg._backends[NativeFamily.MEMPOOL_STORE] = "rust"

        pool = Mempool(max_size=16, min_fee=0.0)
        assert pool.add(_mk_tx("keep", 3.0), signature_preverified=True)

        class _Boom:
            def insert(self, *_a, **_k):
                raise RuntimeError("mempool_store_lock_poisoned")

            def get_sorted(self, *_a, **_k):
                raise RuntimeError("mempool_store_lock_poisoned")

            def hashes(self):
                raise RuntimeError("mempool_store_lock_poisoned")

        pool._native_store = _Boom()
        pool._store_backend = "rust"
        assert pool.add(_mk_tx("after", 5.0), signature_preverified=True)
        assert pool._native_store is None
        assert pool.get_stats().get("store_demoted") is True
    finally:
        reg.reset_for_tests()
        bootstrap_native_capabilities()


def test_bridge_reject_emit_failure_is_visible():
    from bridge.adapter import RustBridgeAdapter

    class _Bus:
        def emit(self, *_a, **_k):
            raise RuntimeError("bus_down")

    class _Db:
        def get_meta(self, *_a, **_k):
            return None

        def set_meta(self, *_a, **_k):
            return None

    class _Inner:
        bus = _Bus()
        db = _Db()

        def confirm_incoming(self, *_a, **_k):
            raise AssertionError("must not credit on reject")

    class _RejectAll(InboundMessageValidator):
        def __init__(self):
            pass

        def validate(self, envelope):
            return ValidationResult(ok=False, reason="zk_invalid", replay_key="rk1")

    br = RustBridgeAdapter(_Inner(), validator=_RejectAll())
    e = InboundEnvelope(
        from_chain="ethereum",
        to_addr="0xrecv",
        amount=1.0,
        event_tx_hash="0xbad",
        log_index=0,
        oracle_meta={},
        zk_proof={"valid": False},
    )
    res = br.confirm_incoming(e)
    assert res.ok is False
    assert res.status == InboundStatus.REJECTED.value
    assert "bus_down" in str(res.detail.get("event_bus_emit_failed") or "")


def test_libp2p_dial_refuses_without_rust():
    """Stub dial must refuse even when the wheel has libp2p (force no-native)."""
    on = Libp2pTransportAdapter(enabled=True)
    try:
        on._native_capable = False
        with pytest.raises(
            TransportCapabilityError, match="stub dial removed|requires abs_native"
        ):
            on.connect(PeerEndpoint(host="127.0.0.1", port=4001, peer_id="lab"))
    finally:
        on.close()
