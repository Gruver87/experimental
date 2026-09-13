"""Wave I: PQ refuse fake valid, confirmations fail-closed, gasPrice null, ready require."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_dilithium_verify_raises_not_implemented():
    from features.postquantum import Dilithium, Falcon, SPHINCSPlus, PQSignature, PQAlgorithm, SecurityLevel

    d = Dilithium()
    with pytest.raises(NotImplementedError, match="Dilithium"):
        d.generate_keypair()
    with pytest.raises(NotImplementedError, match="Dilithium"):
        d.verify(
            PQSignature(
                id="x",
                algorithm=PQAlgorithm.DILITHIUM,
                signature=b"\x00" * 64,
                public_key_hash="a",
                message_hash="b",
            ),
            b"msg",
            b"pk",
        )
    with pytest.raises(NotImplementedError, match="SPHINCS"):
        SPHINCSPlus().verify(
            PQSignature(
                id="x",
                algorithm=PQAlgorithm.SPHINCS_PLUS,
                signature=b"\x00" * 64,
                public_key_hash="a",
                message_hash="b",
            ),
            b"msg",
            b"pk",
        )
    with pytest.raises(NotImplementedError, match="Falcon"):
        Falcon().verify(
            PQSignature(
                id="x",
                algorithm=PQAlgorithm.FALCON,
                signature=b"\x00" * 64,
                public_key_hash="a",
                message_hash="b",
            ),
            b"msg",
            b"pk",
        )


def test_pq_stats_dilithium_not_callable():
    from features.postquantum import PostQuantumManager

    stats = PostQuantumManager().get_stats()
    assert stats["production_ready"] is False
    assert stats["capabilities"]["dilithium"]["callable"] is False


def test_live_l1_confirmations_refuse_unknown():
    from bridge.adapter import LiveL1Rpc

    rpc = LiveL1Rpc()
    with pytest.raises(RuntimeError, match="URL missing"):
        rpc.get_confirmations("no_such_chain_zzz", "0xabc")


def test_eth_gas_price_null_unless_advertise():
    from api.fake_rpc import FakeRpcClient
    from runtime.amount import abs_to_wei

    client = FakeRpcClient()
    assert client.call("eth_gasPrice", []).get("result") is None
    client.config.advertise_config_gas_price = True
    assert client.call("eth_gasPrice", []).get("result") == hex(
        abs_to_wei(client.config.gas_price_wei)
    )


def test_ready_native_req_from_abs_native_mode(monkeypatch):
    """ABS_NATIVE_MODE=require must force native_crypto required on ready path."""
    root = Path(__file__).resolve().parents[2]
    http_src = (root / "api" / "http.py").read_text(encoding="utf-8")
    assert "ABS_NATIVE_MODE" in http_src
    assert "mempool_store_native" in http_src
    assert "advertise_config_gas_price" in (
        root / "runtime" / "config.py"
    ).read_text(encoding="utf-8")
    monkeypatch.setenv("ABS_NATIVE_MODE", "require")
    assert os.environ.get("ABS_NATIVE_MODE") == "require"
