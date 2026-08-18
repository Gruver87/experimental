# network/peer_manager.py
"""Isolated peer mesh registry: lists, scoring, strikes, bans, admission (P2P Point 3).

Owns peer lifecycle policy so ``p2p_node.P2PNode`` can stay on socket I/O + routing.
``PeerConnection`` objects remain owned by the node (I/O); this manager stores
references and enforces mesh policy.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, runtime_checkable

_logger = logging.getLogger("PeerManager")

ClosePeerFn = Callable[[Any], None]
SubnetHelpers = Optional[Any]  # crypto.native module with p2p_ip_is_public / p2p_subnet_key


def peer_health_score(
    *,
    height_gap: int,
    last_seen_age: float,
    health_timeout: float,
    strikes: int = 0,
    import_fails: int = 0,
) -> int:
    """Soft peer quality score for eviction / eclipse prune (0..100)."""
    score = 100
    score -= min(45, int(height_gap) * 15)
    if last_seen_age >= health_timeout:
        score -= 50
    elif last_seen_age >= health_timeout / 2:
        score -= 20
    score -= min(48, max(0, int(strikes)) * 12)
    score -= min(40, max(0, int(import_fails)) * 10)
    return max(0, min(100, score))


@runtime_checkable
class PeerLike(Protocol):
    peer_id: str
    host: str
    port: int
    listen_port: int
    last_seen: float
    connected_at: float
    height: int
    head: str
    quality_import_fails: int


@dataclass
class PeerManagerSettings:
    max_peers: int = 50
    rate_limit_strikes: int = 5
    ban_seconds: int = 300
    peer_timeout: float = 30.0
    evict_min_score: int = 0
    eclipse_warn_ratio: float = 0.0
    bootstrap_peers: List[str] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: Any) -> "PeerManagerSettings":
        return cls(
            max_peers=int(getattr(config, "max_peers", 50) or 50),
            rate_limit_strikes=int(getattr(config, "p2p_rate_limit_strikes", 5) or 5),
            ban_seconds=int(getattr(config, "p2p_ban_seconds", 300) or 300),
            peer_timeout=float(getattr(config, "peer_timeout", 30) or 30),
            evict_min_score=int(getattr(config, "p2p_evict_min_score", 0) or 0),
            eclipse_warn_ratio=float(getattr(config, "p2p_eclipse_warn_ratio", 0) or 0),
            bootstrap_peers=list(getattr(config, "bootstrap_peers", []) or []),
        )


@dataclass
class AdmitDecision:
    allowed: bool
    reason: str = ""
    replaced: bool = False


def preferred_inbound_for(local_node_id: str, remote_node_id: str) -> Optional[bool]:
    """Canonical dial ownership: lower id owns outbound, higher owns inbound.

    Returns True if local should keep inbound, False if local should keep outbound,
    or None when ids are missing/equal (no direction preference).
    """
    local = str(local_node_id or "").strip()
    remote = str(remote_node_id or "").strip()
    if not local or not remote or local == remote:
        return None
    return local > remote


@dataclass
class EclipseTelemetry:
    public_peers: int = 0
    unique_public_subnets: int = 0
    eclipse_ratio: float = 0.0
    at_risk: bool = False
    densest_subnet: str = ""
    prune_total: int = 0


class PeerManager:
    """Mesh registry + strike/ban/score/admission policy.

    Thread-safety: peer map is asyncio-loop oriented; native ``rl_table``
    access is serialized via optional ``rl_lock`` (shared with egress prepare).
    """

    def __init__(
        self,
        settings: PeerManagerSettings,
        *,
        rl_table: Any = None,
        rl_lock: Any = None,
        conn_governor: Any = None,
        native_helpers: SubnetHelpers = None,
        on_shape_reject: Optional[Callable[[str], None]] = None,
    ):
        self.settings = settings
        self._rl_table = rl_table
        self._rl_lock = rl_lock
        self._conn_governor = conn_governor
        self._native = native_helpers
        self._on_shape_reject = on_shape_reject

        self._peers: Dict[str, Any] = {}
        self._known_addrs: List[str] = []
        self._strikes: Dict[str, int] = {}
        self._bans: Dict[str, float] = {}
        self._shape_reject_counts: Dict[str, int] = {}
        self.eclipse = EclipseTelemetry()

        for addr in settings.bootstrap_peers:
            self.remember_addr(addr)

    # ── live map ─────────────────────────────────────────────────────────────

    @property
    def peers(self) -> Dict[str, Any]:
        return self._peers

    @property
    def known_addrs(self) -> List[str]:
        return self._known_addrs

    @property
    def strikes(self) -> Dict[str, int]:
        return self._strikes

    @property
    def bans(self) -> Dict[str, float]:
        return self._bans

    @property
    def shape_reject_counts(self) -> Dict[str, int]:
        return self._shape_reject_counts

    def peer_count(self) -> int:
        return len(self._peers)

    def get(self, peer_id: str) -> Optional[Any]:
        return self._peers.get(peer_id)

    def values(self) -> Iterable[Any]:
        return self._peers.values()

    def items(self):
        return self._peers.items()

    def clear(self, *, close: bool = True) -> None:
        if close:
            for peer in list(self._peers.values()):
                self._safe_close(peer, context="clear")
        self._peers.clear()

    # ── identity / bans ──────────────────────────────────────────────────────

    def peer_key(self, peer: Any) -> str:
        if getattr(peer, "peer_id", None):
            return str(peer.peer_id)
        port = int(getattr(peer, "listen_port", 0) or getattr(peer, "port", 0) or 0)
        return f"{getattr(peer, 'host', '')}:{port}"

    def _bump_shape(self, reason: str) -> None:
        key = str(reason or "unknown")
        self._shape_reject_counts[key] = int(self._shape_reject_counts.get(key, 0) or 0) + 1
        if self._on_shape_reject is not None:
            try:
                self._on_shape_reject(key)
            except Exception as exc:
                _logger.warning("[PeerManager] shape reject hook failed: %s", exc)

    def _safe_close(self, peer: Any, *, context: str) -> None:
        try:
            peer.close()
        except Exception as exc:
            _logger.debug("[PeerManager] close failed (%s): %s", context, exc)

    def note_shape_reject(self, reason: str) -> None:
        """Count a shape/rate reject without strike/ban escalation (soft-refuse path)."""
        self._bump_shape(reason)

    def _rl_call(self, fn, *args, **kwargs):
        """Serialize native rate-limit table access with egress prepare."""
        lock = getattr(self, "_rl_lock", None)
        if lock is None:
            return fn(*args, **kwargs)
        with lock:
            return fn(*args, **kwargs)

    def is_banned(self, key: str, *, now: Optional[float] = None) -> bool:
        if not key:
            return False
        ts = float(now if now is not None else time.time())
        if self._rl_table is not None:
            def _check():
                return bool(self._rl_table.is_banned(str(key), float(ts)))

            banned = bool(self._rl_call(_check))
            if not banned:
                self._bans.pop(key, None)
            return banned
        until = self._bans.get(key)
        if until is None:
            return False
        if ts >= until:
            self._bans.pop(key, None)
            return False
        return True

    def is_addr_banned(self, host: str, port: int, *, now: Optional[float] = None) -> bool:
        ts = float(now if now is not None else time.time())
        if self._rl_table is not None:
            def _check():
                return bool(self._rl_table.is_addr_banned(str(host), int(port), float(ts)))

            return bool(self._rl_call(_check))
        if self.is_banned(f"{host}:{port}", now=ts):
            return True
        return any(
            self.is_banned(key, now=ts)
            for key in self._bans
            if key.startswith(f"{host}:")
        )

    def strike(self, peer: Any, reason: str, *, now: Optional[float] = None) -> bool:
        """Record abuse strike. Returns True if peer is (now) banned and should disconnect."""
        key = self.peer_key(peer)
        if not key:
            return False
        reason_key = str(reason or "unknown")
        self._bump_shape(reason_key)
        max_strikes = int(self.settings.rate_limit_strikes)
        ban_sec = int(self.settings.ban_seconds)
        ts = float(now if now is not None else time.time())

        if self._rl_table is not None:
            def _strike():
                banned = bool(self._rl_table.strike(str(key), float(ts)))
                if not banned:
                    return False, int(self._rl_table.strike_count(str(key))), None
                until = self._rl_table.ban_until(str(key))
                return True, 0, until

            banned, strikes, until = self._rl_call(_strike)
            if not banned:
                self._strikes[key] = strikes
                _logger.warning(
                    "[PeerManager] strike %s/%s for %s (%s)",
                    strikes,
                    max_strikes,
                    key,
                    reason_key,
                )
                return False
            if until is not None:
                self._bans[key] = float(until)
            else:
                self._bans[key] = ts + max(30, ban_sec)
            self._strikes.pop(key, None)
            _logger.warning("[PeerManager] banned %s for %ss (%s)", key, ban_sec, reason)
            return True

        strikes = int(self._strikes.get(key, 0) or 0) + 1
        self._strikes[key] = strikes
        if strikes < max_strikes:
            _logger.warning(
                "[PeerManager] strike %s/%s for %s (%s)",
                strikes,
                max_strikes,
                key,
                reason_key,
            )
            return False
        self._bans[key] = ts + max(30, ban_sec)
        self._strikes.pop(key, None)
        _logger.warning("[PeerManager] banned %s for %ss (%s)", key, ban_sec, reason)
        return True

    def strike_count(self, peer: Any) -> int:
        key = self.peer_key(peer)
        if not key:
            return 0
        strikes = int(self._strikes.get(key, 0) or 0)
        if self._rl_table is not None:
            try:
                def _count():
                    return int(self._rl_table.strike_count(str(key)))

                strikes = max(strikes, int(self._rl_call(_count)))
            except Exception as exc:
                _logger.debug("[PeerManager] strike_count native failed: %s", exc)
        return strikes

    def note_import_fail(self, peer: Optional[Any]) -> None:
        if peer is None:
            return
        peer.quality_import_fails = int(getattr(peer, "quality_import_fails", 0) or 0) + 1

    def score(
        self,
        peer: Any,
        *,
        local_height: int,
        health_timeout: Optional[float] = None,
        now: Optional[float] = None,
    ) -> int:
        ts = float(now if now is not None else time.time())
        timeout = float(
            health_timeout
            if health_timeout is not None
            else max(30.0, float(self.settings.peer_timeout) * 2)
        )
        gap = abs(int(getattr(peer, "height", 0) or 0) - int(local_height or 0))
        age = max(0.0, ts - float(getattr(peer, "last_seen", ts) or ts))
        return peer_health_score(
            height_gap=gap,
            last_seen_age=age,
            health_timeout=timeout,
            strikes=self.strike_count(peer),
            import_fails=int(getattr(peer, "quality_import_fails", 0) or 0),
        )

    # ── admission / slots ────────────────────────────────────────────────────

    def allow_inbound(self, host: str) -> AdmitDecision:
        if self.is_addr_banned(host, 0) and self._rl_table is None:
            # port-agnostic host ban check via prefix when no native table
            if any(self.is_banned(k) for k in self._bans if k.startswith(f"{host}:")):
                return AdmitDecision(False, "banned")
        if self._conn_governor is not None:
            deny = self._conn_governor.allow_inbound(len(self._peers), str(host or ""))
            if deny:
                reason = str(deny)
                self._bump_shape(reason)
                return AdmitDecision(False, reason)
            return AdmitDecision(True)
        if len(self._peers) >= int(self.settings.max_peers):
            self._bump_shape("max_peers")
            return AdmitDecision(False, "max_peers")
        return AdmitDecision(True)

    def allow_outbound(self) -> AdmitDecision:
        if self._conn_governor is not None:
            deny = self._conn_governor.allow_outbound(len(self._peers))
            if deny:
                return AdmitDecision(False, str(deny))
            return AdmitDecision(True)
        if len(self._peers) >= int(self.settings.max_peers):
            return AdmitDecision(False, "max_peers")
        return AdmitDecision(True)

    def has_active_endpoint(self, host: str, port: int) -> bool:
        return any(
            p.host == host and (p.port == port or getattr(p, "listen_port", 0) == port)
            for p in self._peers.values()
        )

    def register(
        self,
        peer: Any,
        *,
        inbound: bool = False,
        replace_stale: bool = True,
        stale_after: Optional[float] = None,
        local_node_id: str = "",
    ) -> AdmitDecision:
        """Insert peer into the live map after handshake.

        Duplicate same ``peer_id`` uses lexicographic dial ownership when
        ``local_node_id`` is set: keep the canonical direction so simultaneous
        A↔B dials cannot tear down both live registrations.
        """
        peer_id = str(getattr(peer, "peer_id", "") or "")
        if not peer_id:
            return AdmitDecision(False, "missing_peer_id")
        if self.is_banned(peer_id) or self.is_banned(self.peer_key(peer)):
            return AdmitDecision(False, "banned")

        replaced = False
        old = self._peers.get(peer_id)
        if old is not None and old is not peer:
            # Lexicographic dial ownership: keep the canonical direction so
            # simultaneous A↔B dials cannot tear down both live registrations.
            prefer_in = preferred_inbound_for(local_node_id, peer_id)
            if prefer_in is not None:
                cand_ok = bool(inbound) is bool(prefer_in)
                old_ok = bool(getattr(old, "_inbound", False)) is bool(prefer_in)
                if cand_ok and not old_ok:
                    # Install challenger first so old message_loop unregister is a no-op.
                    self._peers[peer_id] = peer
                    self._safe_close(old, context="replace_canonical")
                    replaced = True
                elif old_ok and not cand_ok:
                    return AdmitDecision(False, "duplicate_noncanonical")
                elif cand_ok and old_ok:
                    # Same canonical direction — keep the older live session.
                    return AdmitDecision(False, "duplicate_peer")
                else:
                    # Neither matches (rare) — fall through to age policy.
                    pass
            if not replaced:
                age = max(
                    15.0,
                    float(
                        stale_after
                        if stale_after is not None
                        else float(self.settings.peer_timeout)
                    ),
                )
                if time.time() - float(getattr(old, "last_seen", 0) or 0) <= age:
                    return AdmitDecision(False, "duplicate_peer")
                if replace_stale:
                    self._peers[peer_id] = peer
                    self._safe_close(old, context="replace_stale")
                    replaced = True
                else:
                    return AdmitDecision(False, "duplicate_peer")

        if not replaced:
            self._peers[peer_id] = peer
        try:
            peer._inbound = bool(inbound)  # type: ignore[attr-defined]
        except Exception as exc:
            _logger.debug("[PeerManager] set _inbound failed: %s", exc)
        if inbound:
            if self._conn_governor is not None:
                try:
                    self._conn_governor.on_connected(str(getattr(peer, "host", "") or ""))
                except Exception as exc:
                    _logger.debug("[PeerManager] governor on_connected failed: %s", exc)
        return AdmitDecision(True, replaced=replaced)

    def unregister(
        self,
        peer_id: str,
        expected: Any = None,
        *,
        close: bool = True,
    ) -> Optional[Any]:
        if expected is not None and self._peers.get(peer_id) is not expected:
            return None
        peer = self._peers.pop(peer_id, None)
        if peer is None:
            return None
        if getattr(peer, "_inbound", False) and self._conn_governor is not None:
            try:
                self._conn_governor.on_disconnected(str(getattr(peer, "host", "") or ""))
            except Exception as exc:
                _logger.debug("[PeerManager] governor on_disconnected failed: %s", exc)
        if close:
            self._safe_close(peer, context="unregister")
        return peer

    # ── discovery bookkeeping ────────────────────────────────────────────────

    def remember_addr(self, addr: str) -> None:
        if not addr or ":" not in addr:
            return
        host, port_s = str(addr).rsplit(":", 1)
        try:
            port = int(port_s)
        except Exception:
            return
        if not host or port <= 0:
            return
        norm = f"{host}:{port}"
        if norm not in self._known_addrs:
            self._known_addrs.append(norm)

    def expire_bans(self, *, now: Optional[float] = None) -> int:
        ts = float(now if now is not None else time.time())
        expired = [k for k, until in self._bans.items() if ts >= float(until)]
        for key in expired:
            self._bans.pop(key, None)
        return len(expired)

    # ── prune / eclipse ──────────────────────────────────────────────────────

    def health_timeout(self) -> float:
        return max(30.0, float(self.settings.peer_timeout) * 2)

    def prune_stale(
        self,
        *,
        local_height: int,
        max_age: Optional[float] = None,
        now: Optional[float] = None,
    ) -> int:
        """Drop stale / low-score peers. Returns number removed."""
        ts = float(now if now is not None else time.time())
        age_limit = float(
            max_age if max_age is not None else self.health_timeout()
        )
        removed = 0
        health_timeout = self.health_timeout()
        evict_below = int(self.settings.evict_min_score)
        for pid, peer in list(self._peers.items()):
            if ts - float(getattr(peer, "last_seen", ts) or ts) > age_limit:
                self.unregister(pid, peer)
                removed += 1
                continue
            if evict_below > 0 and len(self._peers) > 1:
                score = self.score(
                    peer,
                    local_height=local_height,
                    health_timeout=health_timeout,
                    now=ts,
                )
                if score < evict_below:
                    self.unregister(pid, peer)
                    removed += 1
        removed += self.maybe_eclipse_prune(
            local_height=local_height, health_timeout=health_timeout, now=ts
        )
        self.expire_bans(now=ts)
        return removed

    def refresh_eclipse_snapshot(self, *, now: Optional[float] = None) -> Dict[str, Any]:
        warn = float(self.settings.eclipse_warn_ratio)
        empty = {
            "public_peers": 0,
            "unique_public_subnets": 0,
            "eclipse_ratio": 0.0,
            "at_risk": False,
            "densest_subnet": "",
        }
        if self._conn_governor is None or not hasattr(
            self._conn_governor, "diversity_snapshot"
        ):
            self.eclipse = EclipseTelemetry(prune_total=self.eclipse.prune_total)
            return empty
        ips = [str(getattr(p, "host", "") or "") for p in self._peers.values()]
        try:
            snap = self._conn_governor.diversity_snapshot(ips, warn)
        except Exception as exc:
            _logger.debug("[PeerManager] diversity_snapshot failed: %s", exc)
            return empty
        self.eclipse.public_peers = int(snap.get("public_peers", 0) or 0)
        self.eclipse.unique_public_subnets = int(
            snap.get("unique_public_subnets", 0) or 0
        )
        self.eclipse.eclipse_ratio = float(snap.get("eclipse_ratio", 0) or 0)
        self.eclipse.at_risk = bool(snap.get("at_risk"))
        return snap

    def maybe_eclipse_prune(
        self,
        *,
        local_height: int,
        health_timeout: Optional[float] = None,
        now: Optional[float] = None,
    ) -> int:
        warn = float(self.settings.eclipse_warn_ratio)
        if warn <= 0 or len(self._peers) <= 1 or self._conn_governor is None:
            self.refresh_eclipse_snapshot(now=now)
            return 0
        snap = self.refresh_eclipse_snapshot(now=now)
        if not snap.get("at_risk"):
            return 0
        densest = str(snap.get("densest_subnet") or "")
        native = self._native
        if not densest or native is None:
            return 0
        if not hasattr(native, "p2p_subnet_key") or not hasattr(native, "p2p_ip_is_public"):
            return 0
        timeout = float(health_timeout if health_timeout is not None else self.health_timeout())
        candidates = []
        for pid, peer in self._peers.items():
            host = str(getattr(peer, "host", "") or "")
            try:
                if not native.p2p_ip_is_public(host):
                    continue
                if native.p2p_subnet_key(host) != densest:
                    continue
            except Exception as exc:
                _logger.debug("[PeerManager] eclipse subnet probe failed: %s", exc)
                continue
            score = self.score(
                peer, local_height=local_height, health_timeout=timeout, now=now
            )
            candidates.append((score, pid, peer))
        if not candidates:
            return 0
        candidates.sort(key=lambda t: (t[0], t[1]))
        score, pid, peer = candidates[0]
        self.unregister(pid, peer)
        self.eclipse.prune_total += 1
        _logger.warning(
            "[PeerManager] eclipse prune peer=%s score=%s subnet=%s ratio=%.3f",
            str(pid)[:12],
            score,
            densest,
            float(snap.get("eclipse_ratio", 0) or 0),
        )
        return 1

    # ── views ────────────────────────────────────────────────────────────────

    def peers_info(self, *, now: Optional[float] = None) -> List[Dict[str, Any]]:
        ts = float(now if now is not None else time.time())
        return [
            {
                "id": p.peer_id,
                "host": p.host,
                "port": p.port,
                "listen_port": getattr(p, "listen_port", 0),
                "height": getattr(p, "height", 0),
                "head": getattr(p, "head", "") or "",
                "connected_for": int(ts - float(getattr(p, "connected_at", ts) or ts)),
                "last_seen_age": round(
                    max(0.0, ts - float(getattr(p, "last_seen", ts) or ts)), 3
                ),
            }
            for p in self._peers.values()
        ]

    def active_bans_snapshot(self, *, now: Optional[float] = None) -> Dict[str, Any]:
        ts = float(now if now is not None else time.time())
        if self._rl_table is not None:
            def _snap():
                active_bans = []
                for key in self._rl_table.ban_keys():
                    until = self._rl_table.ban_until(key)
                    if until is None or until <= ts:
                        continue
                    if not self._rl_table.is_banned(key, float(ts)):
                        continue
                    active_bans.append(
                        {"key": key, "seconds_remaining": max(0, int(until - ts))}
                    )
                tracked = int(self._rl_table.tracked_strikes())
                return active_bans, tracked

            active_bans, tracked = self._rl_call(_snap)
        else:
            active_bans = [
                {"key": key, "seconds_remaining": max(0, int(until - ts))}
                for key, until in self._bans.items()
                if until > ts
            ]
            tracked = len(self._strikes)
        return {
            "active_bans": active_bans,
            "tracked_strikes": tracked,
            "ban_seconds": int(self.settings.ban_seconds),
            "strikes_before_ban": int(self.settings.rate_limit_strikes),
            "evict_min_score": int(self.settings.evict_min_score),
            "max_peers": int(self.settings.max_peers),
            "peer_count": self.peer_count(),
            "known_addresses": list(self._known_addrs),
            "shape_rejects": dict(self._shape_reject_counts),
            "eclipse": {
                "public_peers": self.eclipse.public_peers,
                "unique_public_subnets": self.eclipse.unique_public_subnets,
                "eclipse_ratio": self.eclipse.eclipse_ratio,
                "at_risk": self.eclipse.at_risk,
                "prune_total": self.eclipse.prune_total,
            },
        }

    def retain_strike_keys(self, live_keys: Iterable[str]) -> None:
        """Drop strike rows for peers no longer relevant (maintenance)."""
        keep = set(live_keys)
        for key in list(self._strikes.keys()):
            if key not in keep and not self.is_banned(key):
                # keep recent strike history only for live or banned keys
                if key not in {self.peer_key(p) for p in self._peers.values()}:
                    # soft retain: only purge if no ban and not in keep
                    if key not in keep:
                        self._strikes.pop(key, None)
