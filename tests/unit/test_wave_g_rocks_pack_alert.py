"""Wave G: pack-fallback alert + /health/ready honesty fields."""

from __future__ import annotations

from pathlib import Path


def test_alerts_yml_has_rocks_pack_fallback():
    root = Path(__file__).resolve().parents[2]
    alerts = (root / "deploy" / "prometheus" / "alerts.yml").read_text(encoding="utf-8")
    assert "AbsoluteRocksNativePackFallbacks" in alerts
    assert "abs_rocksdb_native_pack_fallbacks" in alerts


def test_http_ready_exposes_honesty_fields():
    root = Path(__file__).resolve().parents[2]
    src = (root / "api" / "http.py").read_text(encoding="utf-8")
    assert 'payload["mempool_store"]' in src
    assert 'payload["rocks_native_pack_fallbacks"]' in src
    # Must remain informational (not added to checks dict as hard gate).
    assert "Wave G: informational honesty only" in src


def test_health_watch_soft_warns_demote():
    root = Path(__file__).resolve().parents[2]
    hw = (root / "scripts" / "health_watch.ps1").read_text(encoding="utf-8")
    core = (root / "scripts" / "health_watch_core.ps1").read_text(encoding="utf-8")
    assert "MempoolDemoted" in hw or "mempool_demoted" in hw
    assert "Get-MempoolDemotedFlag" in core
    assert "MempoolDemoted" in core


def test_docs_no_longer_claim_phase4_next():
    root = Path(__file__).resolve().parents[2]
    cmds = (root / "docs" / "COMMANDS_REFERENCE.md").read_text(encoding="utf-8")
    assert "Next: Phase 4" not in cmds
    assert "verify_wave_g" in cmds or "Waves A" in cmds
