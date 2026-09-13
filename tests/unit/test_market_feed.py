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
            "items": [
                {"pair": "USD/EUR", "base": "USD", "quote": "EUR", "rate": 0.9},
                {"pair": "EUR/USD", "base": "EUR", "quote": "USD", "rate": 1.11},
            ],
            "usd": [{"pair": "USD/EUR", "base": "USD", "quote": "EUR", "rate": 0.9}],
            "eur": [{"pair": "EUR/USD", "base": "EUR", "quote": "USD", "rate": 1.11}],
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
    assert any(e["id"] == "bcse" and e["tz"] == "Europe/Minsk" for e in snap["exchanges"])
    assert "NOT consensus" in " ".join(snap["honesty"])


def test_byn_convert_via_yahoo(monkeypatch):
    monkeypatch.setattr(
        market_feed,
        "_usd_byn_from_yahoo",
        lambda: {
            "pair": "USD/BYN",
            "base": "USD",
            "quote": "BYN",
            "rate": 3.0,
            "source": "yahoo",
        },
    )
    out = market_feed.convert_fx(10, "USD", "BYN")
    assert out["ok"] is True
    assert out["result"] == 30.0
    assert "yahoo-byn" in out["source"]
    back = market_feed.convert_fx(30, "BYN", "USD")
    assert back["result"] == 10.0


def test_fetch_fx_includes_eur_and_byn(monkeypatch):
    def fake_crosses(base: str):
        if base == "USD":
            return (
                [
                    {
                        "pair": "USD/EUR",
                        "base": "USD",
                        "quote": "EUR",
                        "rate": 0.5,
                        "source": "frankfurter",
                    }
                ],
                "2026-09-13",
            )
        return (
            [
                {
                    "pair": "EUR/USD",
                    "base": "EUR",
                    "quote": "USD",
                    "rate": 2.0,
                    "source": "frankfurter",
                }
            ],
            "2026-09-13",
        )

    monkeypatch.setattr(market_feed, "_frankfurter_crosses", fake_crosses)
    monkeypatch.setattr(
        market_feed,
        "_usd_byn_from_yahoo",
        lambda: {
            "pair": "USD/BYN",
            "base": "USD",
            "quote": "BYN",
            "rate": 3.0,
            "source": "yahoo",
        },
    )
    fx = market_feed._fetch_fx()
    assert fx["usd"][0]["pair"] == "USD/BYN"
    assert fx["eur"][0]["pair"] == "EUR/BYN"
    assert fx["eur"][0]["rate"] == 6.0


def test_console_has_markets_nav():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    html = (root / "web" / "console" / "index.html").read_text(encoding="utf-8")
    assert 'data-view="markets"' in html
    app = (root / "web" / "console" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "renderMarkets" in app
    assert "/market/snapshot" in app
