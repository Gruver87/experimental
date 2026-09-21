#!/usr/bin/env python3
"""v1.3.32 honesty: L1 receipt status, EVM static/corrupt, NFT/PQ/will/multisig."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_l1_receipt_status_required():
    text = Path("bridge/l1_rpc.py").read_text(encoding="utf-8")
    assert "_receipt_status_ok" in text
    assert "status-less" in text
    mock = Path("bridge/mock_l1_rpc.py").read_text(encoding="utf-8")
    assert '"status": "0x1"' in mock


def test_evm_fail_closed_storage_and_static():
    text = Path("execution/evm_adapter.py").read_text(encoding="utf-8")
    assert "_loads_contract_storage" in text
    assert 'error="corrupt_storage"' in text or "corrupt_storage" in text
    assert "invalid_calldata" in text
    assert "static_create_rejected" in text
    assert "read_only=True" in text
    assert "static_selfdestruct_rejected" in text


def test_nft_feature_gate_and_stats():
    main = Path("main.py").read_text(encoding="utf-8")
    assert "feature_nft" in main
    assert "NFT Marketplace: disabled" in main
    nft = Path("features/nft.py").read_text(encoding="utf-8")
    assert "execution_bound" in nft
    assert "on_chain_standard" in nft
    cfg = Path("runtime/config.py").read_text(encoding="utf-8")
    assert 'FEATURE_NFT"' in cfg or "FEATURE_NFT" in cfg
    assert 'self.feature_nft = env_bool("FEATURE_NFT", False)' in cfg


def test_will_force_forbidden_in_prod():
    text = Path("api/http.py").read_text(encoding="utf-8")
    assert "force will execute forbidden in prod" in text


def test_pq_capability_matrix():
    text = Path("features/postquantum.py").read_text(encoding="utf-8")
    assert "educational_only" in text
    assert "nist_ml_dsa" in text
    assert "production_ready" in text
    main = Path("main.py").read_text(encoding="utf-8")
    # Honesty: PQ interfaces exist but backends are NotImplemented (not NIST prod).
    assert "not NIST prod backends" in main or "signing backend required" in main


def test_multisig_honesty_labels():
    text = Path("api/http.py").read_text(encoding="utf-8")
    assert "in_memory_registry" in text
    assert '"execution_bound": False' in text
    main = Path("main.py").read_text(encoding="utf-8")
    assert "execution_bound=false" in main
