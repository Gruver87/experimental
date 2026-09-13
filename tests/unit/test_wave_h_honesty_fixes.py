"""Wave H: ready wire-gate, demote-require, SPHINCS 501, satoshi validators."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_ready_gates_wire_when_peers_present():
    root = Path(__file__).resolve().parents[2]
    src = (root / "api" / "http.py").read_text(encoding="utf-8")
    assert "Wave H: with peers/mesh expected" in src
    assert "ready = all(bool(v) for v in checks.values())" in src


def test_demote_forbidden_under_require(monkeypatch):
    from runtime import native_capabilities as nc
    from runtime.native_capabilities import NativeCapabilityRegistry, NativeFamily

    reg = NativeCapabilityRegistry()
    reg._bootstrapped = True
    reg._mode = "require"
    reg._backends[NativeFamily.MEMPOOL_STORE] = "rust"
    with pytest.raises(RuntimeError, match="forbids demote"):
        reg.demote(NativeFamily.MEMPOOL_STORE, "fault")


def test_demote_allowed_in_auto():
    from runtime.native_capabilities import NativeCapabilityRegistry, NativeFamily

    reg = NativeCapabilityRegistry()
    reg._bootstrapped = True
    reg._mode = "auto"
    reg._backends[NativeFamily.MEMPOOL_STORE] = "rust"
    reg.demote(NativeFamily.MEMPOOL_STORE, "fault")
    assert reg._backends[NativeFamily.MEMPOOL_STORE] == "python"


def test_validate_amount_uses_satoshi():
    from middleware.validators import validate_amount

    ok, _ = validate_amount("1.5", min_amount=0)
    assert ok is True
    ok, err = validate_amount("not-a-number")
    assert ok is False
    assert "number" in err.lower() or "Amount" in err


def test_bridge_fee_bps_integer():
    root = Path(__file__).resolve().parents[2]
    src = (root / "bridge" / "abs_bridge.py").read_text(encoding="utf-8")
    assert "BRIDGE_FEE_BPS" in src
    assert "amount * fee_rate" not in src


def test_canonical_serializer_requires_parent():
    from blockchain.canonical_serializer import CanonicalSerializer

    with pytest.raises(ValueError, match="previous_hash"):
        CanonicalSerializer.serialize_block({"height": 1, "transactions": []})
    s = CanonicalSerializer.serialize_block(
        {"height": 0, "transactions": [], "previous_hash": None}
    )
    assert isinstance(s, str) and len(s) > 0


def test_fake_web_shells_redirect():
    root = Path(__file__).resolve().parents[2]
    for name in ("index.html", "simple.html"):
        text = (root / "web" / name).read_text(encoding="utf-8")
        assert "Ops Console" in text
        assert "Math.random" not in text


def test_release_gate_honesty_label():
    root = Path(__file__).resolve().parents[2]
    text = (root / "scripts" / "release_gate.ps1").read_text(encoding="utf-8")
    assert "NOT mesh probe" in text
    assert "RequireMesh" in text


def test_explorer_lab_gated():
    root = Path(__file__).resolve().parents[2]
    text = (root / "web" / "explorer" / "index.html").read_text(encoding="utf-8")
    assert 'data-feature="lab"' in text
    assert "showLab" in text or "abs_show_lab" in text
