"""Market feed allowlist + FX convert (no secrets; TLS verify)."""

from __future__ import annotations

import pytest

from api import market_feed


def test_http_get_refuses_non_https():
    with pytest.raises(market_feed.MarketFeedError, match="https"):
        market_feed._http_get_json("http://api.coingecko.com/api/v3/ping")


def test_http_get_refuses_unknown_host():
    with pytest.raises(market_feed.MarketFeedError, match="allowlisted"):
        market_feed._http_get_json("https://evil.example/price")


def test_fx_identity():
    out = market_feed.convert_fx(10, "USD", "usd")
    assert out["ok"] is True
    assert out["result"] == 10.0
    assert out["source"] == "identity"


def test_fx_amount_too_large():
    with pytest.raises(market_feed.MarketFeedError):
        market_feed.convert_fx(1e13, "USD", "EUR")


def test_snapshot_structure_with_mocks(monkeypatch):
    monkeypatch.setattr(
        market_feed,
        "_fetch_crypto",
        lambda: {
            "ok": True,
            "items": [{"id": "bitcoin", "price_usd": 1.0, "change_24h_pct": 0.1}],
            "source": "coingecko",
        },
    )
    monkeypatch.setattr(
        market_feed,
        "_fetch_fx",
        lambda: {
            "ok": True,
            "items": [{"pair": "USD/EUR", "rate": 0.9}],
            "source": "frankfurter",
        },
    )
    monkeypatch.setattr(
        market_feed,
        "_fetch_yahoo_basket",
        lambda: {
            "ok": True,
            "items": [{"symbol": "GC=F", "name": "Gold", "kind": "commodity", "price": 2000}],
            "errors": [],
            "source": "yahoo",
        },
    )
    market_feed._cache.clear()
    snap = market_feed.build_market_snapshot()
    assert snap["ok"] is True
    assert snap["crypto"]["items"]
    assert snap["fx"]["items"]
    assert snap["tickers"]["items"]
    assert any(e["id"] == "binance" for e in snap["exchanges"])
    assert "NOT consensus" in " ".join(snap["honesty"])


def test_console_has_markets_nav():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    html = (root / "web" / "console" / "index.html").read_text(encoding="utf-8")
    assert 'data-view="markets"' in html
    app = (root / "web" / "console" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "renderMarkets" in app
    assert "/market/snapshot" in app
