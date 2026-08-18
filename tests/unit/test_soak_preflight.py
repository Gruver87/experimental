#!/usr/bin/env python3
"""Soak preflight wiring tests."""

import importlib.util
import json
import os
import sys
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)


def _load(name: str, rel: str):
    path = os.path.join(ROOT, rel)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_soak_preflight_module_exists():
    assert os.path.isfile(os.path.join(ROOT, "scripts", "soak_preflight.py"))
    assert os.path.isfile(os.path.join(ROOT, "scripts", "start_soak_prod_mesh_48h.ps1"))
    prep = open(
        os.path.join(ROOT, "scripts", "prepare_48h_soak.ps1"), encoding="utf-8"
    ).read()
    baked = open(
        os.path.join(ROOT, "scripts", "check_baked_state_root.py"), encoding="utf-8"
    ).read()
    assert "Last committed canonical root" in baked
    assert "COMMITTED_STATE_ROOT_OK" in prep
    assert "check_baked_state_root.py" in prep
    assert r"\(unhealthy\)" in prep
    assert "print('OK' if" not in prep


def test_check_baked_state_root_on_host(capsys):
    mod = _load("check_baked_state_root", "scripts/check_baked_state_root.py")
    assert mod.main() == 0
    assert "COMMITTED_STATE_ROOT_OK" in capsys.readouterr().out


def test_soak_preflight_detects_unreachable_mesh(monkeypatch):
    mod = _load("soak_preflight", "scripts/soak_preflight.py")

    def _fail_urlopen(*_args, **_kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _fail_urlopen)
    errors, _warnings, meta = mod.run_soak_preflight(hours=48)
    assert errors
    assert meta.get("ready") is False
    assert "start_command" in meta
    assert meta.get("hours_planned") == 48


def test_soak_preflight_accepts_require_wire_probe(monkeypatch):
    mod = _load("soak_preflight", "scripts/soak_preflight.py")

    def _fail_urlopen(*_args, **_kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _fail_urlopen)
    errors, _warnings, meta = mod.run_soak_preflight(
        hours=48, require_p2p_tls=True, require_wire_probe=True
    )
    assert errors
    assert meta.get("require_wire_probe") is True
    assert "start_soak_prod_mesh_48h" in str(meta.get("start_command") or "")


def test_soak_preflight_require_wire_uses_full_harness():
    path = os.path.join(ROOT, "scripts", "soak_preflight.py")
    text = open(path, encoding="utf-8").read()
    assert "quick=False" in text
    assert "peer_timeout=8.0" in text
    assert "attempts = 3 if require_wire_probe else 1" in text


def test_genesis_ceremony_status_missing_manifest():
    from types import SimpleNamespace
    from api.http import _genesis_ceremony_status

    info = _genesis_ceremony_status(SimpleNamespace(validators_manifest_path=""))
    assert info.get("ready") is False


def test_monolith_gate_accepts_soak_preflight_flag():
    mod = _load("monolith_gate", "scripts/monolith_gate.py")
    import inspect

    sig = inspect.signature(mod.run_monolith_gate)
    assert "soak_preflight" in sig.parameters


def test_soak_preflight_write_report(tmp_path, monkeypatch):
    mod = _load("soak_preflight", "scripts/soak_preflight.py")
    monkeypatch.setattr(mod, "ROOT", tmp_path)

    path = mod.write_report([], ["warn"], {"ready": True})
    assert path == tmp_path / "logs" / "soak_preflight.json"
    assert path.is_file()
    payload = path.read_text(encoding="utf-8")
    assert "warn" in payload


def test_summarize_soak_fail_never_claims_pass(tmp_path):
    mod = _load("summarize_soak_fail", "scripts/summarize_soak_fail.py")
    log = tmp_path / "soak.log"
    log.write_text(
        "\n".join(
            [
                "2026-08-16 06:37:21 health_watch start ports=18180,18181,18182 interval=300s full_every=6 log=x",
                "2026-08-16 06:37:30 OK mesh aligned 18180:h1/p2",
                "2026-08-17 12:37:21 FAIL port 18180 status: timeout",
                "2026-08-17 12:37:21 FAIL port 18181 status: timeout",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "passed": True,
                "hours_elapsed": 48.0,
                "hours_requested": 48,
                "health_watch_exit": 1,
                "counts": {"hard_fail_lines": 2},
            }
        ),
        encoding="utf-8",
    )
    payload = mod.summarize(log_path=log, report_path=report)
    assert payload["passed"] is False
    assert payload["fail_lines"] == 2
    assert payload["fails_by_port"]["18180"] == 1
    assert payload["first_fail_hour"] == 30
    assert payload["full_every_logged"] == "6"
    assert payload["report_passed"] is True

