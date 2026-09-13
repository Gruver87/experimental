"""Secure web console static resolve + CSP surface."""

from __future__ import annotations

import os
from pathlib import Path

import api.http as http_mod


ROOT = Path(__file__).resolve().parents[2]


def test_resolve_console_index():
    got = http_mod._resolve_web_static(str(ROOT), "/")
    assert got is not None
    path, ct = got
    assert path.endswith(os.path.join("web", "console", "index.html"))
    assert "html" in ct


def test_resolve_console_asset_js():
    got = http_mod._resolve_web_static(str(ROOT), "/console/assets/app.js")
    assert got is not None
    path, ct = got
    assert path.endswith(os.path.join("web", "console", "assets", "app.js"))
    assert "javascript" in ct


def test_resolve_explorer():
    got = http_mod._resolve_web_static(str(ROOT), "/explorer")
    assert got is not None
    assert got[0].endswith(os.path.join("web", "explorer", "index.html"))


def test_refuse_path_traversal():
    assert http_mod._resolve_web_static(str(ROOT), "/console/../runtime/config.py") is None
    assert http_mod._resolve_web_static(str(ROOT), "/console/assets/../../secrets.env") is None


def test_refuse_unknown_extension_under_console(tmp_path, monkeypatch):
    # Even if a .py sneaks under web/console, extension allowlist refuses it.
    console = ROOT / "web" / "console"
    assert http_mod._resolve_web_static(str(ROOT), "/console/index.py") is None


def test_csp_header_constant():
    assert "default-src 'self'" in http_mod._WEB_CSP
    assert "frame-ancestors 'none'" in http_mod._WEB_CSP
    assert "object-src 'none'" in http_mod._WEB_CSP
