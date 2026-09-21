#!/usr/bin/env python3
"""Monitor must poll slim /status?probe=1 — never full /status HOL."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_monitor_source_uses_probe_not_full_status():
    src = (ROOT / "monitor.py").read_text(encoding="utf-8")
    assert "/status?probe=1" in src
    assert 'requests.get(f"{self.api_url}/status", timeout=' not in src
    assert "debounce_s" in src


def test_get_stats_hits_probe_first():
    from monitor import BlockchainMonitor

    with patch.object(BlockchainMonitor, "_start_monitoring"):
        mon = BlockchainMonitor(api_url="http://127.0.0.1:18080", node_id="t")
    calls = []

    def fake_get(url, timeout=0):
        calls.append((url, timeout))
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "probe": True,
            "height": 42,
            "peers": 2,
            "mempool_size": 0,
        }
        return resp

    with patch("monitor.requests.get", side_effect=fake_get):
        stats = mon._get_stats()
    assert stats["height"] == 42
    assert calls[0][0].endswith("/status?probe=1")
    assert calls[0][1] <= 5


def test_critical_alert_debounced():
    from monitor import BlockchainMonitor

    with patch.object(BlockchainMonitor, "_start_monitoring"):
        mon = BlockchainMonitor(api_url="http://127.0.0.1:18080", node_id="t")
    mon._add_alert("CRITICAL", "API not responding", debounce_s=120.0)
    mon._add_alert("CRITICAL", "API not responding", debounce_s=120.0)
    assert len(mon.alerts) == 1
