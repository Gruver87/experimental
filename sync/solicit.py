"""SyncSolicitHub — solicit waiter table + fulfill/reject (ADR 0003 Step C / D).

Owns waiter semantics (arm / fulfill / reject / stale timeout cleanup).
P2P owns TCP send and ``asyncio.wait_for``; the network dispatcher must only
forward inbound messages into ``fulfill_or_reject`` — it must not inspect
waiter state.

No P2P node module imports.
"""

from __future__ import annotations

import logging
import time
from typing import (
    Any,
    Callable,
    Dict,
    Mapping,
    MutableMapping,
    Optional,
    Tuple,
)

logger = logging.getLogger("Sync.Solicit")

StrikeFn = Callable[[Any, str], bool]
BumpFn = Callable[[str, int], None]

# Wire type strings (parity with network message constants; no network import).
MSG_BLOCK = "block"
MSG_BLOCKS = "blocks"
MSG_MEMPOOL = "mempool"
MSG_PEERS = "peers"
MSG_STATE_ROOT_RESPONSE = "state_root_response"

# Waiter tuple layout: (expected_types, future, request_ctx, armed_at_monotonic)
WaiterTuple = Tuple[tuple, Any, Optional[Mapping[str, Any]], float]

_MSG_KIND = {
    MSG_STATE_ROOT_RESPONSE: "state_root",
    MSG_MEMPOOL: "mempool",
    MSG_BLOCKS: "blocks",
    MSG_BLOCK: "block",
    MSG_PEERS: "peers",
}


def _ctx_kind(request_ctx: Optional[Mapping[str, Any]]) -> str:
    if isinstance(request_ctx, dict):
        return str(request_ctx.get("kind") or "")
    return ""


def _msg_kind(msg_type: str) -> str:
    return _MSG_KIND.get(str(msg_type or ""), "")


class SolicitResult:
    """Outcome of fulfill_or_reject."""

    __slots__ = ("consumed", "detail")

    def __init__(self, consumed: bool, detail: str = "") -> None:
        self.consumed = bool(consumed)
        self.detail = str(detail or "")


def _unpack_waiter(waiter: tuple) -> WaiterTuple:
    """Normalize legacy 3-tuples and current 4-tuples."""
    if len(waiter) >= 4:
        return (
            tuple(waiter[0] or ()),
            waiter[1],
            waiter[2],
            float(waiter[3] or 0.0),
        )
    if len(waiter) >= 3:
        return (
            tuple(waiter[0] or ()),
            waiter[1],
            waiter[2],
            0.0,
        )
    return (tuple(waiter[0] or ()), waiter[1], None, 0.0)


class SyncSolicitHub:
    """Arm / fulfill / timeout solicit-only waiters.

    Waiter value: ``(expected_types, future, request_ctx, armed_at)``.
    """

    __slots__ = (
        "_waiters",
        "_kind_waiters",
        "_peers_solicit_only",
        "_verify_blocks",
        "_verify_block",
        "_verify_state_root",
        "_default_max_age",
        "_timeouts_total",
        "_stale_sweeps_total",
        "_fulfills_total",
        "_rejects_total",
    )

    def __init__(
        self,
        *,
        peers_solicit_only: bool = True,
        verify_blocks: Optional[Callable[..., Any]] = None,
        verify_block: Optional[Callable[..., Any]] = None,
        verify_state_root: Optional[Callable[..., Any]] = None,
        default_max_age_sec: float = 120.0,
    ) -> None:
        self._waiters: Dict[str, tuple] = {}
        # Extra (peer_id, kind) slots so state_root does not wait behind
        # mempool/blocks on the same peer (HTTP 8s STRICT vs 12s mempool).
        self._kind_waiters: Dict[Tuple[str, str], tuple] = {}
        self._peers_solicit_only = bool(peers_solicit_only)
        self._verify_blocks = verify_blocks
        self._verify_block = verify_block
        self._verify_state_root = verify_state_root
        self._default_max_age = float(default_max_age_sec or 120.0)
        self._timeouts_total = 0
        self._stale_sweeps_total = 0
        self._fulfills_total = 0
        self._rejects_total = 0

    @property
    def waiters(self) -> MutableMapping[str, tuple]:
        """Mutable view for back-compat aliases only — prefer arm/clear/timeout."""
        return self._waiters

    @property
    def armed_count(self) -> int:
        return len(self._waiters) + len(self._kind_waiters)

    def set_peers_solicit_only(self, enabled: bool) -> None:
        self._peers_solicit_only = bool(enabled)

    def arm(
        self,
        peer_id: str,
        expected_types: tuple,
        fut: Any,
        request_ctx: Optional[Mapping[str, Any]] = None,
        *,
        armed_at: Optional[float] = None,
    ) -> None:
        pid = str(peer_id or "")
        if not pid:
            raise ValueError("peer_id required to arm solicit waiter")
        ts = float(armed_at) if armed_at is not None else float(time.monotonic())
        entry = (
            tuple(expected_types or ()),
            fut,
            request_ctx,
            ts,
        )
        kind = _ctx_kind(request_ctx)
        primary = self._waiters.get(pid)
        if primary is not None and kind:
            # Park even when kinds match. Overwriting a catch-up 30s
            # state_root waiter with HTTP 8s (or vice versa) abandoned the
            # first future so STRICT harness always lost the reply.
            self._kind_waiters[(pid, kind)] = entry
            return
        if kind:
            self._kind_waiters.pop((pid, kind), None)
        self._waiters[pid] = entry

    def _take_waiter(
        self,
        peer_id: str,
        kind: str = "",
        *,
        fut: Any = None,
    ) -> Optional[tuple]:
        pid = str(peer_id or "")
        k = str(kind or "")
        if fut is not None:
            if k:
                parked = self._kind_waiters.get((pid, k))
                if parked is not None and _unpack_waiter(parked)[1] is fut:
                    return self._kind_waiters.pop((pid, k), None)
            primary = self._waiters.get(pid)
            if primary is not None and _unpack_waiter(primary)[1] is fut:
                return self._waiters.pop(pid, None)
            for key, parked in list(self._kind_waiters.items()):
                if key[0] == pid and _unpack_waiter(parked)[1] is fut:
                    return self._kind_waiters.pop(key, None)
            return None
        if k:
            parked = self._kind_waiters.pop((pid, k), None)
            if parked is not None:
                return parked
            primary = self._waiters.get(pid)
            if primary is not None and _ctx_kind(_unpack_waiter(primary)[2]) == k:
                return self._waiters.pop(pid, None)
            return None
        return self._waiters.pop(pid, None)

    def _find_waiter(self, peer_id: str, msg_type: str) -> Optional[tuple]:
        pid = str(peer_id or "")
        kind = _msg_kind(msg_type)
        if kind:
            parked = self._kind_waiters.get((pid, kind))
            if parked is not None:
                return parked
            primary = self._waiters.get(pid)
            if primary is None:
                return None
            expected_types, _fut, _ctx, _armed = _unpack_waiter(primary)
            try:
                if msg_type in tuple(expected_types or ()):
                    return primary
            except TypeError:
                return None
            return None
        return self._waiters.get(pid)

    def _collect_state_root_waiters(self, peer_id: str) -> list:
        """Primary + parked same-kind state_root waiters (HTTP + catch-up)."""
        pid = str(peer_id or "")
        out: list = []
        seen: set = set()
        parked = self._kind_waiters.get((pid, "state_root"))
        primary = self._waiters.get(pid)
        for waiter in (parked, primary):
            if waiter is None:
                continue
            expected, fut, ctx, _armed = _unpack_waiter(waiter)
            marker = id(fut) if fut is not None else id(waiter)
            if marker in seen:
                continue
            try:
                if MSG_STATE_ROOT_RESPONSE not in tuple(expected or ()):
                    continue
            except TypeError:
                continue
            if not (isinstance(ctx, dict) and ctx.get("kind") == "state_root"):
                continue
            seen.add(marker)
            out.append(waiter)
        # no_waiter → dispatcher handle_unsolicited_state_root
        # strikes unsolicited_state_root_response after late-stash miss.
        return out

    def clear(self, peer_id: str, kind: str = "", *, fut: Any = None) -> None:
        """Drop waiter without touching the future (caller owns timeout result)."""
        self._take_waiter(peer_id, kind, fut=fut)

    def get(self, peer_id: str, kind: str = "") -> Optional[tuple]:
        pid = str(peer_id or "")
        k = str(kind or "")
        if k:
            parked = self._kind_waiters.get((pid, k))
            if parked is not None:
                return parked
            primary = self._waiters.get(pid)
            if primary is not None and _ctx_kind(_unpack_waiter(primary)[2]) == k:
                return primary
            return None
        return self._waiters.get(pid)

    def timeout(
        self,
        peer_id: str,
        *,
        result: Any = None,
        kind: str = "",
        fut: Any = None,
    ) -> bool:
        """Expire one waiter: fulfill future with ``result`` (default None) and clear.

        Returns True if a waiter was present. Pass ``fut`` so HTTP timeout
        cannot steal a parked same-kind catch-up waiter.
        """
        pid = str(peer_id or "")
        waiter = self._take_waiter(pid, kind, fut=fut)
        if waiter is None:
            return False
        _types, fut, _ctx, _armed = _unpack_waiter(waiter)
        if fut is not None and not fut.done():
            try:
                fut.set_result(result)
            except Exception as exc:
                logger.warning("[Solicit] timeout set_result failed peer=%s: %s", pid[:12], exc)
        self._timeouts_total = int(self._timeouts_total or 0) + 1
        return True

    def expire_stale(
        self,
        max_age_sec: Optional[float] = None,
        *,
        now: Optional[float] = None,
    ) -> int:
        """Clear waiters older than ``max_age_sec``; set their futures to None.

        Returns the number of waiters expired. Used for hub-side stale cleanup
        independent of the transport's ``asyncio.wait_for``.
        """
        max_age = float(
            self._default_max_age if max_age_sec is None else max_age_sec
        )
        if max_age < 0:
            max_age = 0.0
        clock = float(now) if now is not None else float(time.monotonic())
        expired: list[tuple[str, str]] = []

        def _stale(waiter: tuple) -> bool:
            _types, _fut, _ctx, armed_at = _unpack_waiter(waiter)
            if armed_at <= 0.0:
                return max_age <= 0.0
            return (clock - float(armed_at)) >= max_age

        for pid, waiter in list(self._waiters.items()):
            if _stale(waiter):
                expired.append((pid, ""))
        for (pid, kind), waiter in list(self._kind_waiters.items()):
            if _stale(waiter):
                expired.append((pid, kind))
        for pid, kind in expired:
            self.timeout(pid, result=None, kind=kind)
        if expired:
            self._stale_sweeps_total = int(self._stale_sweeps_total or 0) + 1
        return len(expired)

    def clear_all(self, *, timeout_futures: bool = False) -> int:
        """Drop every waiter. Optionally fulfill futures with None first."""
        n = len(self._waiters) + len(self._kind_waiters)
        if timeout_futures:
            for pid in list(self._waiters.keys()):
                self.timeout(pid, result=None)
            for pid, kind in list(self._kind_waiters.keys()):
                self.timeout(pid, result=None, kind=kind)
            return n
        self._waiters.clear()
        self._kind_waiters.clear()
        return n

    def mempool_solicit_armed(self, peer_id: str) -> bool:
        waiter = self.get(peer_id, kind="mempool")
        if not waiter:
            return False
        expected_types, _fut, request_ctx, _armed = _unpack_waiter(waiter)
        try:
            types_ok = MSG_MEMPOOL in tuple(expected_types or ())
        except TypeError:
            types_ok = False
        if not types_ok:
            return False
        return isinstance(request_ctx, dict) and request_ctx.get("kind") == "mempool"

    def merge_into_status(self, status: MutableMapping[str, Any]) -> None:
        """Expose hub telemetry into P2P / node status dicts."""
        status["solicit_hub"] = True
        status["solicit_armed"] = int(self.armed_count)
        status["solicit_timeouts_total"] = int(self._timeouts_total or 0)
        status["solicit_stale_sweeps_total"] = int(self._stale_sweeps_total or 0)
        status["solicit_fulfills_total"] = int(self._fulfills_total or 0)
        status["solicit_rejects_total"] = int(self._rejects_total or 0)

    def _fulfill_state_root_waiter(
        self,
        waiter: tuple,
        peer: Any,
        data: Any,
        full_msg: Mapping[str, Any],
        *,
        strike: StrikeFn,
        bump: Callable[[str, int], None],
    ) -> SolicitResult:
        """Apply one state_root response to one waiter (per-ctx verify)."""
        _expected, fut, request_ctx, _armed = _unpack_waiter(waiter)
        if fut is not None and fut.done():
            return SolicitResult(True, "late_state_root")
        if not isinstance(request_ctx, dict) or request_ctx.get("kind") != "state_root":
            return SolicitResult(True, "unsolicited_state_root")
        if self._verify_state_root is not None:
            reason = self._verify_state_root(
                data if isinstance(data, dict) else (data or {}),
                int(request_ctx.get("height", 0) or 0),
                str(request_ctx.get("expected_head") or ""),
            )
            if reason:
                got_h = 0
                if isinstance(data, dict):
                    try:
                        got_h = int(data.get("height", 0) or 0)
                    except (TypeError, ValueError):
                        got_h = 0
                expect_h = int(request_ctx.get("height", 0) or 0)
                if (
                    str(reason) == "bad_state_root_response_height"
                    and 0 < got_h < expect_h
                ):
                    bump("state_root_lag_replies_total", 1)
                    if fut is not None and not fut.done():
                        fut.set_result(full_msg)
                    self._fulfills_total = int(self._fulfills_total or 0) + 1
                    return SolicitResult(True, "state_root_lag")
                bump("state_root_response_request_rejects_total", 1)
                self._rejects_total = int(self._rejects_total or 0) + 1
                strike(peer, str(reason))
                if fut is not None and not fut.done():
                    fut.set_result(None)
                return SolicitResult(True, str(reason))
        expect_root = str(request_ctx.get("expected_state_root") or "").strip()
        if expect_root and isinstance(data, dict):
            got_root = str(data.get("state_root") or "").strip()
            if got_root and got_root.lower() != expect_root.lower():
                bump("state_root_local_rejects_total", 1)
                self._rejects_total = int(self._rejects_total or 0) + 1
                strike(peer, "bad_state_root_response_local_root")
                if fut is not None and not fut.done():
                    fut.set_result(None)
                return SolicitResult(True, "local_root_mismatch")
        if fut is not None and not fut.done():
            fut.set_result(full_msg)
        self._fulfills_total = int(self._fulfills_total or 0) + 1
        return SolicitResult(True, "state_root_ok")

    def fulfill_or_reject(
        self,
        peer: Any,
        msg_type: str,
        data: Any,
        full_msg: Mapping[str, Any],
        *,
        strike: StrikeFn,
        bump: Optional[BumpFn] = None,
    ) -> SolicitResult:
        """Process an inbound message against an armed waiter.

        Returns ``consumed=True`` when the caller must stop (fulfilled or struck).
        Returns ``consumed=False`` when no waiter applies — continue to dispatcher.
        """

        def _bump(name: str, delta: int = 1) -> None:
            if bump is not None:
                bump(name, delta)

        peer_id = str(getattr(peer, "peer_id", "") or "")
        libp2p_id = str(getattr(peer, "_libp2p_peer_id", "") or "")
        if str(msg_type or "") == MSG_STATE_ROOT_RESPONSE and (peer_id or libp2p_id):
            waiters = self._collect_state_root_waiters(peer_id) if peer_id else []
            if not waiters and libp2p_id and libp2p_id != peer_id:
                waiters = self._collect_state_root_waiters(libp2p_id)
            if not waiters:
                return SolicitResult(False, "no_waiter")
            last = SolicitResult(True, "late_state_root")
            for waiter in waiters:
                last = self._fulfill_state_root_waiter(
                    waiter,
                    peer,
                    data,
                    full_msg,
                    strike=strike,
                    bump=_bump,
                )
            return last

        waiter = self._find_waiter(peer_id, str(msg_type or "")) if peer_id else None
        if not waiter:
            # No armed waiter → leave solicit-only unsolicited rejects to dispatcher.
            return SolicitResult(False, "no_waiter")

        expected_types, fut, request_ctx, _armed = _unpack_waiter(waiter)

        if msg_type not in expected_types:
            return SolicitResult(False, "waiter_mismatch")
        if fut.done():
            # Timed-out solicit: late state_root must not ban / soft-refuse-storm;
            # consume so dispatcher does not treat it as unsolicited.
            if msg_type == MSG_STATE_ROOT_RESPONSE:
                return SolicitResult(True, "late_state_root")
            return SolicitResult(False, "waiter_mismatch")

        if (
            msg_type == MSG_BLOCKS
            and isinstance(request_ctx, dict)
            and request_ctx.get("kind") == "blocks"
        ):
            if self._verify_blocks is not None:
                reason = self._verify_blocks(
                    data if isinstance(data, list) else (data or []),
                    int(request_ctx.get("from_height", 0) or 0),
                    int(request_ctx.get("to_height", 0) or 0),
                    str(request_ctx.get("parent_hash") or ""),
                    allow_empty=bool(request_ctx.get("allow_empty", False)),
                )
                if reason:
                    _bump("blocks_response_semantic_rejects_total")
                    self._rejects_total = int(self._rejects_total or 0) + 1
                    strike(peer, str(reason))
                    if not fut.done():
                        fut.set_result(None)
                    return SolicitResult(True, str(reason))
            if not fut.done():
                fut.set_result(full_msg)
            self._fulfills_total = int(self._fulfills_total or 0) + 1
            return SolicitResult(True, "blocks_ok")

        if (
            msg_type == MSG_BLOCK
            and isinstance(request_ctx, dict)
            and request_ctx.get("kind") == "block"
        ):
            if self._verify_block is not None:
                reason = self._verify_block(
                    data,
                    str(request_ctx.get("expected_hash") or ""),
                    allow_null=bool(request_ctx.get("allow_null", True)),
                )
                if reason:
                    _bump("block_response_semantic_rejects_total")
                    self._rejects_total = int(self._rejects_total or 0) + 1
                    strike(peer, str(reason))
                    if not fut.done():
                        fut.set_result(None)
                    return SolicitResult(True, str(reason))
            if not fut.done():
                fut.set_result(full_msg)
            self._fulfills_total = int(self._fulfills_total or 0) + 1
            return SolicitResult(True, "block_ok")

        if msg_type == MSG_MEMPOOL:
            if isinstance(request_ctx, dict) and request_ctx.get("kind") == "mempool":
                if not fut.done():
                    fut.set_result(full_msg)
                self._fulfills_total = int(self._fulfills_total or 0) + 1
                return SolicitResult(True, "mempool_ok")
            _bump("unsolicited_mempool_rejects_total")
            self._rejects_total = int(self._rejects_total or 0) + 1
            strike(peer, "unsolicited_mempool")
            if not fut.done():
                fut.set_result(None)
            return SolicitResult(True, "unsolicited_mempool")

        if msg_type == MSG_BLOCKS:
            if isinstance(request_ctx, dict) and request_ctx.get("kind") == "blocks":
                if not fut.done():
                    fut.set_result(full_msg)
                self._fulfills_total = int(self._fulfills_total or 0) + 1
                return SolicitResult(True, "blocks_ok")
            _bump("unsolicited_block_rejects_total")
            self._rejects_total = int(self._rejects_total or 0) + 1
            strike(peer, "unsolicited_blocks")
            if not fut.done():
                fut.set_result(None)
            return SolicitResult(True, "unsolicited_blocks")

        if msg_type == MSG_BLOCK:
            if isinstance(request_ctx, dict) and request_ctx.get("kind") == "block":
                if not fut.done():
                    fut.set_result(full_msg)
                self._fulfills_total = int(self._fulfills_total or 0) + 1
                return SolicitResult(True, "block_ok")
            _bump("unsolicited_block_rejects_total")
            self._rejects_total = int(self._rejects_total or 0) + 1
            strike(peer, "unsolicited_block")
            if not fut.done():
                fut.set_result(None)
            return SolicitResult(True, "unsolicited_block")

        if msg_type == MSG_PEERS:
            if isinstance(request_ctx, dict) and request_ctx.get("kind") == "peers":
                if not fut.done():
                    fut.set_result(full_msg)
                self._fulfills_total = int(self._fulfills_total or 0) + 1
                return SolicitResult(True, "peers_ok")
            if self._peers_solicit_only:
                _bump("unsolicited_peers_rejects_total")
                self._rejects_total = int(self._rejects_total or 0) + 1
                strike(peer, "unsolicited_peers")
                if not fut.done():
                    fut.set_result(None)
                return SolicitResult(True, "unsolicited_peers")
            if not fut.done():
                fut.set_result(full_msg)
            self._fulfills_total = int(self._fulfills_total or 0) + 1
            return SolicitResult(True, "peers_push_ok")

        if not fut.done():
            fut.set_result(full_msg)
        self._fulfills_total = int(self._fulfills_total or 0) + 1
        return SolicitResult(True, "generic_fulfill")
