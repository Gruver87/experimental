#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ops-console market snapshot (non-consensus).

Allowlisted HTTPS upstreams only, TLS verify on, short timeouts, in-process
cache. Not L1 truth — operator orientation for FX / crypto / macro tickers.
"""

from __future__ import annotations

import json
import logging
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("market_feed")

_CACHE_TTL_SEC = 45.0
_HTTP_TIMEOUT_SEC = 6.0
_MAX_BODY = 512_000

_ALLOWED_HOSTS = frozenset(
    {
        "api.coingecko.com",
        "api.frankfurter.app",
        "query1.finance.yahoo.com",
    }
)

_CRYPTO_IDS = (
    "bitcoin",
    "ethereum",
    "solana",
    "binancecoin",
    "ripple",
    "cardano",
    "dogecoin",
    "tether",
    "usd-coin",
    "pax-gold",
    "chainlink",
    "avalanche-2",
)

_YAHOO_SYMBOLS: Tuple[Tuple[str, str, str], ...] = (
    ("GC=F", "Gold", "commodity"),
    ("SI=F", "Silver", "commodity"),
    ("CL=F", "WTI Crude", "commodity"),
    ("BZ=F", "Brent Crude", "commodity"),
    ("NG=F", "Natural Gas", "commodity"),
    ("HG=F", "Copper", "commodity"),
    ("DX-Y.NYB", "US Dollar Index", "fx"),
    ("^GSPC", "S&P 500", "index"),
    ("^IXIC", "Nasdaq", "index"),
    ("^DJI", "Dow Jones", "index"),
    ("^VIX", "VIX", "index"),
    ("AAPL", "Apple", "equity"),
    ("MSFT", "Microsoft", "equity"),
    ("NVDA", "NVIDIA", "equity"),
    ("TSLA", "Tesla", "equity"),
    ("AMZN", "Amazon", "equity"),
    ("GOOGL", "Alphabet", "equity"),
    ("META", "Meta", "equity"),
    ("BTC-USD", "Bitcoin (Yahoo)", "crypto"),
    ("ETH-USD", "Ethereum (Yahoo)", "crypto"),
)

_FX_QUOTES = (
    "EUR",
    "GBP",
    "JPY",
    "CHF",
    "CNY",
    "AUD",
    "CAD",
    "HKD",
    "SGD",
    "KRW",
    "INR",
    "BRL",
    "TRY",
    "AED",
    "RUB",
    "PLN",
    "SEK",
    "NOK",
    "MXN",
    "ZAR",
)

_EXCHANGES: Tuple[Dict[str, Any], ...] = (
    {
        "id": "nyse",
        "name": "NYSE / Nasdaq",
        "city": "New York",
        "tz": "America/New_York",
        "open": "09:30",
        "close": "16:00",
        "kind": "equity",
    },
    {
        "id": "cme",
        "name": "CME Globex",
        "city": "Chicago",
        "tz": "America/Chicago",
        "open": "17:00",
        "close": "16:00",
        "kind": "futures",
        "note": "Nearly 24h; brief daily break",
    },
    {
        "id": "lse",
        "name": "LSE",
        "city": "London",
        "tz": "Europe/London",
        "open": "08:00",
        "close": "16:30",
        "kind": "equity",
    },
    {
        "id": "xetra",
        "name": "Xetra (Frankfurt)",
        "city": "Frankfurt",
        "tz": "Europe/Berlin",
        "open": "09:00",
        "close": "17:30",
        "kind": "equity",
    },
    {
        "id": "moex",
        "name": "MOEX",
        "city": "Moscow",
        "tz": "Europe/Moscow",
        "open": "10:00",
        "close": "18:50",
        "kind": "equity",
    },
    {
        "id": "tse",
        "name": "TSE / JPX",
        "city": "Tokyo",
        "tz": "Asia/Tokyo",
        "open": "09:00",
        "close": "15:00",
        "kind": "equity",
    },
    {
        "id": "hkex",
        "name": "HKEX",
        "city": "Hong Kong",
        "tz": "Asia/Hong_Kong",
        "open": "09:30",
        "close": "16:00",
        "kind": "equity",
    },
    {
        "id": "sse",
        "name": "SSE / SZSE",
        "city": "Shanghai",
        "tz": "Asia/Shanghai",
        "open": "09:30",
        "close": "15:00",
        "kind": "equity",
    },
    {
        "id": "asx",
        "name": "ASX",
        "city": "Sydney",
        "tz": "Australia/Sydney",
        "open": "10:00",
        "close": "16:00",
        "kind": "equity",
    },
    {
        "id": "binance",
        "name": "Binance",
        "city": "Global",
        "tz": "UTC",
        "open": "00:00",
        "close": "23:59",
        "kind": "crypto",
        "always_open": True,
    },
    {
        "id": "coinbase",
        "name": "Coinbase",
        "city": "Global",
        "tz": "America/Los_Angeles",
        "open": "00:00",
        "close": "23:59",
        "kind": "crypto",
        "always_open": True,
    },
    {
        "id": "bybit",
        "name": "Bybit",
        "city": "Global",
        "tz": "UTC",
        "open": "00:00",
        "close": "23:59",
        "kind": "crypto",
        "always_open": True,
    },
    {
        "id": "kraken",
        "name": "Kraken",
        "city": "Global",
        "tz": "UTC",
        "open": "00:00",
        "close": "23:59",
        "kind": "crypto",
        "always_open": True,
    },
    {
        "id": "okx",
        "name": "OKX",
        "city": "Global",
        "tz": "UTC",
        "open": "00:00",
        "close": "23:59",
        "kind": "crypto",
        "always_open": True,
    },
)

_lock = threading.Lock()
_cache: Dict[str, Tuple[float, Any]] = {}
_ssl_ctx = ssl.create_default_context()


class MarketFeedError(Exception):
    """Upstream market fetch refused or failed."""


def _cache_get(key: str) -> Optional[Any]:
    row = _cache.get(key)
    if not row:
        return None
    ts, val = row
    if time.time() - ts > _CACHE_TTL_SEC:
        return None
    return val


def _cache_set(key: str, val: Any) -> None:
    _cache[key] = (time.time(), val)


def _http_get_json(url: str) -> Any:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise MarketFeedError("only https upstreams allowed")
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise MarketFeedError(f"host not allowlisted: {host}")
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AbsoluteOpsConsole/1.0 (+industrial; market-orientation)",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            req, timeout=_HTTP_TIMEOUT_SEC, context=_ssl_ctx
        ) as resp:
            raw = resp.read(_MAX_BODY + 1)
    except urllib.error.HTTPError as exc:
        raise MarketFeedError(f"upstream HTTP {exc.code}") from exc
    except Exception as exc:
        raise MarketFeedError(f"upstream fetch failed: {exc}") from exc
    if len(raw) > _MAX_BODY:
        raise MarketFeedError("upstream body too large")
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MarketFeedError(f"upstream JSON invalid: {exc}") from exc


def _fetch_crypto() -> Dict[str, Any]:
    ids = ",".join(_CRYPTO_IDS)
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={urllib.parse.quote(ids)}"
        "&vs_currencies=usd&include_24hr_change=true"
    )
    data = _http_get_json(url)
    out: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        for cid in _CRYPTO_IDS:
            row = data.get(cid) or {}
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": cid,
                    "symbol": cid,
                    "price_usd": row.get("usd"),
                    "change_24h_pct": row.get("usd_24h_change"),
                    "source": "coingecko",
                }
            )
    return {"ok": True, "items": out, "source": "coingecko"}


def _fetch_fx() -> Dict[str, Any]:
    to = ",".join(_FX_QUOTES)
    url = f"https://api.frankfurter.app/latest?from=USD&to={urllib.parse.quote(to)}"
    data = _http_get_json(url)
    rates = data.get("rates") if isinstance(data, dict) else {}
    items = []
    if isinstance(rates, dict):
        for cur, rate in rates.items():
            items.append(
                {
                    "pair": f"USD/{cur}",
                    "base": "USD",
                    "quote": cur,
                    "rate": rate,
                    "source": "frankfurter",
                }
            )
    return {
        "ok": True,
        "as_of": (data or {}).get("date") if isinstance(data, dict) else None,
        "base": "USD",
        "items": items,
        "source": "frankfurter",
    }


def _yahoo_quote(symbol: str) -> Optional[Dict[str, Any]]:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(symbol, safe='=^.-')}"
        "?interval=1d&range=5d"
    )
    data = _http_get_json(url)
    try:
        result = (((data or {}).get("chart") or {}).get("result") or [None])[0]
        if not result:
            return None
        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        change_pct = None
        if price is not None and prev not in (None, 0):
            change_pct = ((float(price) - float(prev)) / float(prev)) * 100.0
        return {
            "symbol": symbol,
            "price": price,
            "currency": meta.get("currency"),
            "change_pct": change_pct,
            "exchange": meta.get("exchangeName"),
            "source": "yahoo",
        }
    except Exception:
        return None


def _fetch_yahoo_basket() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    for symbol, name, kind in _YAHOO_SYMBOLS:
        try:
            q = _yahoo_quote(symbol)
            if not q:
                errors.append(f"{symbol}:empty")
                continue
            q["name"] = name
            q["kind"] = kind
            items.append(q)
        except MarketFeedError as exc:
            errors.append(f"{symbol}:{exc}")
        except Exception as exc:
            errors.append(f"{symbol}:{exc}")
    return {
        "ok": bool(items),
        "items": items,
        "errors": errors[:12],
        "source": "yahoo",
    }


def convert_fx(amount: float, frm: str, to: str) -> Dict[str, Any]:
    frm_u = (frm or "USD").strip().upper()
    to_u = (to or "EUR").strip().upper()
    if frm_u == to_u:
        return {
            "ok": True,
            "amount": float(amount),
            "from": frm_u,
            "to": to_u,
            "rate": 1.0,
            "result": float(amount),
            "source": "identity",
        }
    if abs(float(amount)) > 1e12:
        raise MarketFeedError("amount too large")
    key = f"fx:{frm_u}:{to_u}:{amount}"
    with _lock:
        hit = _cache_get(key)
        if hit is not None:
            return hit
    url = (
        "https://api.frankfurter.app/latest"
        f"?amount={urllib.parse.quote(str(amount))}"
        f"&from={urllib.parse.quote(frm_u)}"
        f"&to={urllib.parse.quote(to_u)}"
    )
    data = _http_get_json(url)
    rates = (data or {}).get("rates") if isinstance(data, dict) else {}
    if not isinstance(rates, dict) or to_u not in rates:
        raise MarketFeedError("fx pair unavailable")
    out = {
        "ok": True,
        "amount": float(amount),
        "from": frm_u,
        "to": to_u,
        "rate": float(rates[to_u]) / float(amount) if float(amount) else None,
        "result": float(rates[to_u]),
        "as_of": (data or {}).get("date"),
        "source": "frankfurter",
    }
    with _lock:
        _cache_set(key, out)
    return out


def build_market_snapshot() -> Dict[str, Any]:
    """Aggregate crypto + FX + yahoo basket. Soft-fail per section."""
    with _lock:
        hit = _cache_get("snapshot")
        if hit is not None:
            out = dict(hit)
            out["cache"] = "hit"
            return out

    crypto: Dict[str, Any] = {"ok": False, "items": [], "error": None}
    fx: Dict[str, Any] = {"ok": False, "items": [], "error": None}
    yahoo: Dict[str, Any] = {"ok": False, "items": [], "error": None}

    try:
        crypto = _fetch_crypto()
    except Exception as exc:
        logger.info("market crypto fetch failed: %s", exc)
        crypto = {"ok": False, "items": [], "error": str(exc), "source": "coingecko"}

    try:
        fx = _fetch_fx()
    except Exception as exc:
        logger.info("market fx fetch failed: %s", exc)
        fx = {"ok": False, "items": [], "error": str(exc), "source": "frankfurter"}

    try:
        yahoo = _fetch_yahoo_basket()
    except Exception as exc:
        logger.info("market yahoo fetch failed: %s", exc)
        yahoo = {"ok": False, "items": [], "error": str(exc), "source": "yahoo"}

    snap = {
        "ok": bool(crypto.get("ok") or fx.get("ok") or yahoo.get("ok")),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ttl_sec": _CACHE_TTL_SEC,
        "honesty": [
            "NOT consensus / NOT Absolute price oracle",
            "Third-party public feeds; may lag or fail",
            "No API keys; TLS verify on; host allowlist only",
        ],
        "exchanges": list(_EXCHANGES),
        "crypto": crypto,
        "fx": fx,
        "tickers": yahoo,
        "cache": "miss",
        "upstreams": sorted(_ALLOWED_HOSTS),
    }
    with _lock:
        _cache_set("snapshot", snap)
    return snap
