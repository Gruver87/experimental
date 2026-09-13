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
    ("BYN=X", "USD/BYN", "fx"),
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
        "id": "bcse",
        "name": "BCSE (Belarus)",
        "city": "Minsk",
        "tz": "Europe/Minsk",
        "open": "10:00",
        "close": "17:00",
        "kind": "equity",
        "note": "Belarusian Currency and Stock Exchange",
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


def _usd_byn_from_yahoo() -> Optional[Dict[str, Any]]:
    """BYN is not on ECB/Frankfurter — use Yahoo BYN=X (USD/BYN)."""
    q = _yahoo_quote("BYN=X")
    if not q or q.get("price") is None:
        return None
    return {
        "pair": "USD/BYN",
        "base": "USD",
        "quote": "BYN",
        "rate": float(q["price"]),
        "change_pct": q.get("change_pct"),
        "source": "yahoo",
    }


def _frankfurter_crosses(base: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Fetch USD or EUR crosses from Frankfurter (ECB)."""
    base_u = base.strip().upper()
    quotes = [c for c in _FX_QUOTES if c != base_u]
    if base_u == "EUR" and "USD" not in quotes:
        quotes = ["USD"] + quotes
    to = ",".join(quotes)
    url = (
        "https://api.frankfurter.app/latest"
        f"?from={urllib.parse.quote(base_u)}&to={urllib.parse.quote(to)}"
    )
    data = _http_get_json(url)
    rates = data.get("rates") if isinstance(data, dict) else {}
    items: List[Dict[str, Any]] = []
    if isinstance(rates, dict):
        for cur, rate in rates.items():
            items.append(
                {
                    "pair": f"{base_u}/{cur}",
                    "base": base_u,
                    "quote": cur,
                    "rate": rate,
                    "source": "frankfurter",
                }
            )
    as_of = (data or {}).get("date") if isinstance(data, dict) else None
    return items, as_of


def _fetch_fx() -> Dict[str, Any]:
    usd_items, as_of = _frankfurter_crosses("USD")
    eur_items: List[Dict[str, Any]] = []
    try:
        eur_items, eur_as_of = _frankfurter_crosses("EUR")
        as_of = as_of or eur_as_of
    except Exception as exc:
        logger.info("market EUR crosses fetch failed: %s", exc)

    byn = None
    try:
        byn = _usd_byn_from_yahoo()
    except Exception as exc:
        logger.info("market BYN fetch failed: %s", exc)

    if byn is not None:
        usd_items.insert(0, byn)
        # EUR/BYN = (USD/BYN) / (USD/EUR) when USD/EUR present
        usd_eur = next(
            (float(r["rate"]) for r in usd_items if r.get("quote") == "EUR"),
            None,
        )
        if usd_eur is None:
            usd_eur = next(
                (
                    (1.0 / float(r["rate"]))
                    for r in eur_items
                    if r.get("quote") == "USD" and float(r["rate"])
                ),
                None,
            )
        if usd_eur and usd_eur > 0:
            eur_items.insert(
                0,
                {
                    "pair": "EUR/BYN",
                    "base": "EUR",
                    "quote": "BYN",
                    "rate": float(byn["rate"]) / usd_eur,
                    "source": "yahoo+frankfurter",
                },
            )

    return {
        "ok": True,
        "as_of": as_of,
        "base": "USD+EUR",
        "items": usd_items + eur_items,
        "usd": usd_items,
        "eur": eur_items,
        "source": "frankfurter+yahoo-byn",
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


def _fx_via_usd(amount: float, frm_u: str, to_u: str) -> Dict[str, Any]:
    """Triangle via USD when one leg is BYN (Yahoo) or Frankfurter misses a pair."""
    amt = float(amount)
    if frm_u == "USD":
        usd_amt = amt
        src_legs = []
    elif to_u == "USD" and frm_u == "BYN":
        byn = _usd_byn_from_yahoo()
        if byn is None:
            raise MarketFeedError("BYN rate unavailable")
        rate = float(byn["rate"])
        if rate <= 0:
            raise MarketFeedError("BYN rate invalid")
        result = amt / rate
        return {
            "ok": True,
            "amount": amt,
            "from": frm_u,
            "to": to_u,
            "rate": 1.0 / rate,
            "result": result,
            "source": "yahoo-byn",
        }
    else:
        # frm -> USD via Frankfurter (or BYN->USD)
        if frm_u == "BYN":
            mid = _fx_via_usd(amt, "BYN", "USD")
            usd_amt = float(mid["result"])
            src_legs = ["yahoo-byn"]
        else:
            url = (
                "https://api.frankfurter.app/latest"
                f"?amount={urllib.parse.quote(str(amt))}"
                f"&from={urllib.parse.quote(frm_u)}&to=USD"
            )
            data = _http_get_json(url)
            rates = (data or {}).get("rates") if isinstance(data, dict) else {}
            if not isinstance(rates, dict) or "USD" not in rates:
                raise MarketFeedError("fx pair unavailable")
            usd_amt = float(rates["USD"])
            src_legs = ["frankfurter"]

    if to_u == "USD":
        return {
            "ok": True,
            "amount": amt,
            "from": frm_u,
            "to": to_u,
            "rate": (usd_amt / amt) if amt else None,
            "result": usd_amt,
            "source": "+".join(src_legs) or "identity",
        }

    if to_u == "BYN":
        byn = _usd_byn_from_yahoo()
        if byn is None:
            raise MarketFeedError("BYN rate unavailable")
        rate = float(byn["rate"])
        if rate <= 0:
            raise MarketFeedError("BYN rate invalid")
        result = usd_amt * rate
        legs = (src_legs + ["yahoo-byn"]) if src_legs else ["yahoo-byn"]
        return {
            "ok": True,
            "amount": amt,
            "from": frm_u,
            "to": to_u,
            "rate": (result / amt) if amt else None,
            "result": result,
            "source": "+".join(legs),
        }

    url = (
        "https://api.frankfurter.app/latest"
        f"?amount={urllib.parse.quote(str(usd_amt))}"
        f"&from=USD&to={urllib.parse.quote(to_u)}"
    )
    data = _http_get_json(url)
    rates = (data or {}).get("rates") if isinstance(data, dict) else {}
    if not isinstance(rates, dict) or to_u not in rates:
        raise MarketFeedError("fx pair unavailable")
    result = float(rates[to_u])
    legs = (src_legs + ["frankfurter"]) if src_legs else ["frankfurter"]
    return {
        "ok": True,
        "amount": amt,
        "from": frm_u,
        "to": to_u,
        "rate": (result / amt) if amt else None,
        "result": result,
        "as_of": (data or {}).get("date"),
        "source": "+".join(legs),
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
    if "BYN" in (frm_u, to_u):
        out = _fx_via_usd(float(amount), frm_u, to_u)
        with _lock:
            _cache_set(key, out)
        return out
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
