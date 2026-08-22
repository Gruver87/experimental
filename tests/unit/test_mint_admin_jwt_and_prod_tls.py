#!/usr/bin/env python3
"""mint_admin_jwt + prod_gate TLS coverage."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_mint_admin_jwt_script(monkeypatch, tmp_path):
    monkeypatch.setenv("JWT_SECRET", "unit-test-mint-admin-jwt-secret-32b")
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "mint_admin_jwt.py"),
            "--address",
            "ops-test",
            "--hours",
            "1",
            "--role",
            "admin",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    token = proc.stdout.strip()
    assert token.count(".") == 2

    import importlib
    import middleware.jwt_auth as jwt_mod

    importlib.reload(jwt_mod)
    jwt_mod.jwt_auth.secret_key = os.environ["JWT_SECRET"]
    ok, payload, err = jwt_mod.jwt_auth.require_role(token, role="admin")
    assert ok, err
    assert payload["address"] == "ops-test"
    assert payload["role"] == "admin"


def test_prod_gate_requires_tls_on_tcp_profiles():
    from prod_gate import PROD_FILES, check_file

    for path in PROD_FILES:
        errors = check_file(path)
        tls_errs = [e for e in errors if "p2p_tls" in e]
        assert not tls_errs, f"{path}: {tls_errs}"
        raw = json.loads((ROOT / path).read_text(encoding="utf-8"))
        if raw.get("feature_libp2p") is True:
            assert raw.get("p2p_tls_enabled") is False
        else:
            assert raw.get("p2p_tls_enabled") is True
            assert raw.get("p2p_tls_require_client_cert") is True
