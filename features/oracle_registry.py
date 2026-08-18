"""On-chain oracle feed registry — signed submissions persisted in SQLite."""
from __future__ import annotations

from crypto import native
import json
import os
import time
from typing import Any, Dict, List, Optional

from bridge.oracle_auth import sign_payload, verify_signature
from runtime.amount import parse_finite_number


class OracleFeedRegistry:
    """Stores price/weather feeds with optional HMAC attestation."""

    def __init__(self, db, secret: Optional[str] = None):
        self.db = db
        # None → inherit BRIDGE_ORACLE_SECRET; explicit "" disables HMAC (unit/dev).
        if secret is None:
            self.secret = str(os.environ.get("BRIDGE_ORACLE_SECRET", "") or "").strip()
        else:
            self.secret = str(secret).strip()

    def _feed_id(self, symbol: str, source: str, submitted_at: int) -> str:
        raw = f"{symbol}:{source}:{submitted_at}"
        return native.sha256_hex(raw.encode())[:32]

    def submit_feed(
        self,
        symbol: str,
        value: float,
        source: str = "reporter",
        reporter: str = "",
        signature: str = "",
        payload: Optional[Dict[str, Any]] = None,
        require_signature: bool = True,
    ) -> Dict[str, Any]:
        symbol = (symbol or "").strip().lower()
        if not symbol:
            return {"ok": False, "error": "symbol required"}
        try:
            value = parse_finite_number(value, field="value")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        body = payload or {
            "symbol": symbol,
            "value": value,
            "source": source,
            "reporter": reporter,
            "ts": int(time.time()),
        }
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        if require_signature:
            if not self.secret:
                return {"ok": False, "error": "oracle secret not configured"}
            if not signature or not verify_signature(self.secret, raw, signature):
                return {"ok": False, "error": "invalid oracle signature"}
        ts = int(body.get("ts", time.time()))
        feed_id = self._feed_id(symbol, source, ts)
        height = int(self.db.get_chain_tip() if hasattr(self.db, "get_chain_tip") else 0)
        self.db.save_oracle_feed(
            feed_id=feed_id,
            symbol=symbol,
            value=value,
            source=source,
            reporter=reporter,
            signature=signature or "",
            payload=json.dumps(body),
            block_height=height,
            submitted_at=ts,
        )
        return {"ok": True, "feed_id": feed_id, "symbol": symbol, "value": value}

    def ingest_internal(self, symbol: str, value: float, source: str, meta: Optional[Dict] = None) -> str:
        """Persist feed from live oracle manager (no HMAC — tier offchain)."""
        value = parse_finite_number(value, field="value")
        ts = int(time.time())
        feed_id = self._feed_id(symbol, source, ts)
        body = {"symbol": symbol, "value": value, "source": source, "ts": ts}
        if meta:
            body.update(meta)
        height = int(self.db.get_chain_tip() if hasattr(self.db, "get_chain_tip") else 0)
        self.db.save_oracle_feed(
            feed_id=feed_id,
            symbol=symbol.lower(),
            value=value,
            source=source,
            reporter="internal",
            signature="",
            payload=json.dumps(body),
            block_height=height,
            submitted_at=ts,
        )
        return feed_id

    def sync_from_manager(self, oracle_manager) -> int:
        """Snapshot latest prices from OracleManager into registry."""
        if not oracle_manager:
            return 0
        count = 0
        for sym in ("bitcoin", "ethereum", "solana"):
            p = oracle_manager.get_crypto_price(sym)
            if p:
                self.ingest_internal(sym, p.price, getattr(p, "source", "coingecko"), {
                    "change_24h": getattr(p, "change_24h", 0),
                    "volume": getattr(p, "volume", 0),
                })
                count += 1
        if hasattr(oracle_manager, "get_abs_reference_price"):
            abs_p = oracle_manager.get_abs_reference_price()
            if abs_p:
                self.ingest_internal("absolute", abs_p.price, abs_p.source, {
                    "change_24h": abs_p.change_24h,
                })
                count += 1
        return count

    def list_feeds(self, symbol: str = "", limit: int = 50) -> List[Dict]:
        return self.db.get_oracle_feeds(symbol=symbol, limit=limit)

    def latest_by_symbol(self, symbol: str) -> Optional[Dict]:
        rows = self.list_feeds(symbol=symbol, limit=1)
        return rows[0] if rows else None

    def submit_report(
        self,
        symbol: str,
        value: float,
        reporter: str,
        signature: str = "",
        payload: Optional[Dict[str, Any]] = None,
        *,
        max_age_sec: int = 300,
    ) -> Dict[str, Any]:
        """Reporter submission for quorum aggregation."""
        symbol = (symbol or "").strip().lower()
        if not symbol or not reporter:
            return {"ok": False, "error": "symbol and reporter required"}
        try:
            value = parse_finite_number(value, field="value")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        now = int(time.time())
        body = payload or {
            "symbol": symbol,
            "value": value,
            "reporter": reporter,
            "ts": now,
        }
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        # When a secret is configured, unsigned reports must not count toward quorum.
        if self.secret:
            if not signature:
                return {"ok": False, "error": "oracle signature required"}
            if not verify_signature(self.secret, raw, signature):
                return {"ok": False, "error": "invalid oracle signature"}
        elif signature:
            # Signature provided without a configured secret cannot be verified.
            return {"ok": False, "error": "oracle secret not configured"}
        ts = int(body.get("ts", now))
        if abs(now - ts) > max(30, int(max_age_sec or 300)):
            return {"ok": False, "error": "stale or future oracle report"}
        report_id = native.sha256_hex(f"{symbol}:{reporter}:{ts}".encode())[:32]
        if hasattr(self.db, "save_oracle_report"):
            self.db.save_oracle_report({
                "report_id": report_id,
                "symbol": symbol,
                "reporter": reporter,
                "value": value,
                "signature": signature or "",
                "payload": json.dumps(body),
                "submitted_at": ts,
            })
        return {"ok": True, "report_id": report_id, "symbol": symbol, "value": value}

    def aggregate_symbol(
        self,
        symbol: str,
        *,
        quorum: int = 2,
        max_age_sec: int = 300,
        max_deviation_pct: float = 5.0,
    ) -> Optional[Dict[str, Any]]:
        """Median price from recent unique reporters (quorum gate)."""
        symbol = (symbol or "").strip().lower()
        if not symbol or not hasattr(self.db, "get_oracle_reports"):
            return None
        cutoff = int(time.time()) - max(30, max_age_sec)
        rows = self.db.get_oracle_reports(symbol=symbol, since=cutoff, limit=50)
        # One vote per reporter — keep the latest submission.
        by_reporter: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            rep = str(r.get("reporter") or "")
            if not rep:
                continue
            prev = by_reporter.get(rep)
            if prev is None or int(r.get("submitted_at", 0) or 0) >= int(
                prev.get("submitted_at", 0) or 0
            ):
                by_reporter[rep] = r
        unique = list(by_reporter.values())
        if len(unique) < quorum:
            return None
        values = sorted(float(r["value"]) for r in unique)
        mid = values[len(values) // 2]
        if len(values) >= 2:
            dev = abs(values[-1] - values[0]) / max(mid, 1e-9) * 100.0
            if dev > max_deviation_pct:
                return None
        canonical = self.ingest_internal(symbol, mid, "quorum_median", {
            "quorum": len(unique),
            "reporters": [r["reporter"] for r in unique[:5]],
        })
        return {
            "symbol": symbol,
            "value": mid,
            "quorum": len(unique),
            "unique_reporters": len(unique),
            "feed_id": canonical,
            "source": "quorum_median",
        }

    def sign_payload(self, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return sign_payload(self.secret, raw)
