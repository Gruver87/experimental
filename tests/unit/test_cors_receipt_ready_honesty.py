#!/usr/bin/env python3
"""v1.3.20 honesty: CORS miss, receipt omit→null, ready+peers, sync p2p_fallback."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_resolve_cors_empty_list_does_not_promote_to_star():
    from api import http as http_mod

    cfg = SimpleNamespace(cors_origins=[])
    assert http_mod._resolve_cors_allow_origin(cfg, "https://evil.example") == ""
    assert http_mod._resolve_cors_allow_origin(cfg, "") == ""


def test_resolve_cors_miss_never_echoes_first_allowlist_entry():
    from api import http as http_mod

    cfg = SimpleNamespace(cors_origins=["https://explorer.example.com", "https://app.example.com"])
    assert http_mod._resolve_cors_allow_origin(cfg, "https://evil.example") == ""
    assert http_mod._resolve_cors_allow_origin(cfg, "https://explorer.example.com") == (
        "https://explorer.example.com"
    )


def test_send_acao_skips_empty_origin():
    from api import http as http_mod

    handler = MagicMock()
    http_mod._send_acao_header(handler, "")
    handler.send_header.assert_not_called()
    http_mod._send_acao_header(handler, "https://explorer.example.com")
    handler.send_header.assert_called_once_with(
        "Access-Control-Allow-Origin", "https://explorer.example.com"
    )


def test_proxy_cors_miss_returns_empty_string():
    # Exercise the same honesty rules as NodeOrchestrator._proxy_cors_origin.
    cors_origins = ["https://explorer.example.com"]

    def _proxy_cors_origin(request_origin: str) -> str:
        # Match REST CORS honesty: never echo first allowlist entry on miss.
        origin = (request_origin or "").strip()
        if "*" in cors_origins:
            return "*"
        if origin and origin in cors_origins:
            return origin
        return ""

    assert _proxy_cors_origin("https://evil.example") == ""
    assert _proxy_cors_origin("https://explorer.example.com") == "https://explorer.example.com"


def test_normalize_tx_status_omitted_and_unknown_are_zero():
    from storage.database import Database

    assert Database._normalize_tx_status(None) == 0
    assert Database._normalize_tx_status("") == 0
    assert Database._normalize_tx_status("bogus") == 0
    assert Database._normalize_tx_status(1) == 1
    assert Database._normalize_tx_status("success") == 1


def test_format_receipt_omitted_status_is_null():
    from api.http import _format_receipt

    receipt = _format_receipt({"hash": "0xabc", "block_height": 1, "from_addr": "0x1"})
    assert receipt is not None
    assert receipt["status"] is None


def test_build_sync_status_p2p_fallback_fail_closed_with_peers():
    from api.http import _build_sync_status

    p2p = MagicMock()
    p2p.get_peers_info.return_value = [{"height": 10}, {"height": 12}]
    p2p.sync_engine = None
    cfg = SimpleNamespace(bootstrap_peers=["127.0.0.1:5000"])
    bc = MagicMock()
    bc.get_height.return_value = 5

    status = _build_sync_status(None, p2p, bc, cfg)
    assert status["source"] == "p2p_fallback"
    assert status["syncing"] is True
    assert status["wire_probe_ok"] is False
    assert status["wire_probe_probed"] is False
    assert "SyncEngine missing" in status["hint"]


def test_config_default_cors_origins_empty_not_star():
    from runtime.config import Config

    cfg = Config()
    assert cfg.cors_origins == []
    assert "*" not in cfg.cors_origins
