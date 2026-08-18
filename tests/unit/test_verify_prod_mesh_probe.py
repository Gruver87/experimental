#!/usr/bin/env python3
"""Prod mesh probe verification tests."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "scripts" / "verify_prod_mesh_probe.py"
    spec = importlib.util.spec_from_file_location("verify_prod_mesh_probe", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_prod_mesh_probe_scripts_exist():
    assert (ROOT / "scripts" / "verify_prod_mesh_probe.py").is_file()
    assert (ROOT / "scripts" / "probe_prod_mesh.ps1").is_file()
    assert (ROOT / "scripts" / "prod_mesh_resilience_suite.ps1").is_file()


def test_ceremony_evidence_scripts_exist():
    assert (ROOT / "scripts" / "ceremony_evidence_suite.ps1").is_file()
    assert (ROOT / "scripts" / "prepare_ceremony_deploy.ps1").is_file()


def test_unreachable_nodes_fail():
    mod = _load()
    with patch.object(mod, "_probe_ready", return_value=False):
        errors, _warnings, meta = mod.verify_prod_mesh_probe(wait_sec=0)
    assert meta["reachable"] == 0
    assert len(errors) == 3


def test_aligned_mesh_ok_with_mocks():
    mod = _load()
    ready = {"status": "ready"}
    status = {"chain_id": 778888, "height": 10, "peers": 2, "deployment_mode": "prod", "head_hash": "0xabc"}
    harness = {"harness_healthy": True, "tip_state_aligned": True, "live_state_root": "0xroot"}
    topo = {"topology_healthy": True, "peer_count": 2}

    def fake_api(url, timeout=10.0):
        if "/health/ready" in url:
            return ready
        if "/status" in url:
            return status
        if "/p2p/topology" in url:
            return topo
        return harness

    with patch.object(mod, "_api", side_effect=fake_api), patch.object(mod, "_probe_ready", return_value=True):
        errors, _warnings, meta = mod.verify_prod_mesh_probe(wait_sec=0)
    assert errors == []
    assert meta["reachable"] == 3


def test_head_mismatch_retries_then_ok():
    mod = _load()
    calls = {"n": 0}

    def fake_api(url, timeout=10.0):
        if "/health/ready" in url:
            return {"status": "ready"}
        if "/status" in url:
            calls["n"] += 1
            if calls["n"] <= 3:
                # First pass: one node still on previous tip (mining window).
                if "18181" in url:
                    return {
                        "chain_id": 778888,
                        "height": 10,
                        "peers": 2,
                        "deployment_mode": "prod",
                        "head_hash": "0xold",
                    }
            return {
                "chain_id": 778888,
                "height": 11,
                "peers": 2,
                "deployment_mode": "prod",
                "head_hash": "0xnew",
            }
        return {}

    with (
        patch.object(mod, "_api", side_effect=fake_api),
        patch.object(mod, "_probe_ready", return_value=True),
        patch.object(mod, "ALIGN_STATUS_SLEEP_SEC", 0),
    ):
        errors, _warnings, meta = mod.verify_prod_mesh_probe(wait_sec=0, deep=False)
    assert errors == []
    assert meta["reachable"] == 3


def test_persistent_head_mismatch_still_fails():
    mod = _load()

    def fake_api(url, timeout=10.0):
        if "/health/ready" in url:
            return {"status": "ready"}
        if "/status" in url:
            h = "0xa" if "18180" in url else "0xb"
            return {
                "chain_id": 778888,
                "height": 10,
                "peers": 2,
                "deployment_mode": "prod",
                "head_hash": h,
            }
        return {}

    with (
        patch.object(mod, "_api", side_effect=fake_api),
        patch.object(mod, "_probe_ready", return_value=True),
        patch.object(mod, "ALIGN_STATUS_SLEEP_SEC", 0),
    ):
        errors, _warnings, _meta = mod.verify_prod_mesh_probe(wait_sec=0, deep=False)
    assert any("head hash mismatch" in e for e in errors)
