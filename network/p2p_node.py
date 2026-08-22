#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2P Network — TCP-сеть для синхронизации блоков и транзакций.

Протокол: JSON-сообщения через asyncio TCP сокеты.
Возможности:
  - Handshake (проверка chain_id)
  - Анонс и получение блоков (block gossip)
  - Трансляция транзакций (tx gossip)
  - Синхронизация цепочки (sync)
  - Обмен списком пиров (peer discovery)
"""

import asyncio
import json
import math
import time
import threading
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple

from network.p2p_tls import (
    bootstrap_pin_map,
    build_p2p_client_ssl_context,
    build_p2p_server_ssl_context,
    extract_peer_tls_meta,
    fingerprint_allowlist,
    handshake_node_id_matches_cert,
    p2p_tls_enabled,
    p2p_tls_status,
    validate_p2p_tls_config,
)
from crypto import native
from runtime.amount import parse_p2p_wire_abs
from network.peer_manager import (
    PeerManager,
    PeerManagerSettings,
    peer_health_score as _peer_health_score,
)

logger = logging.getLogger("P2P")

# Fail closed on oversized wire payloads (DoS hardening).
DEFAULT_MAX_P2P_LINE_BYTES = 2 * 1024 * 1024


def should_defer_tip_safety_skip_ahead(
    *,
    apply_busy: bool,
    candidate_height: int,
    tip_height: int,
) -> bool:
    """True when skip-ahead is the local forge pipeline, not a long-range jump.

    Miner can have tip+1 in the apply queue and already gossip tip+2. Tip-safety
    seeing committed tip then refuses tip_unknown_parent. Import still runs on
    the serial queue and ``_validate_block_structure`` rejects a real gap.
    Only defer exactly tip+2 while the queue is busy.
    """
    if not apply_busy:
        return False
    try:
        cand = int(candidate_height)
        tip = int(tip_height)
    except (TypeError, ValueError):
        return False
    return cand == tip + 2


class WireReject:
    """Sentinel from Peer.recv: parse/shape reject (not EOF)."""

    __slots__ = ("reason",)

    def __init__(self, reason: str):
        self.reason = str(reason or "bad_wire_line")


def _max_p2p_line_bytes(config) -> int:
    raw = getattr(config, "p2p_max_message_bytes", None)
    if raw is None:
        return DEFAULT_MAX_P2P_LINE_BYTES
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_P2P_LINE_BYTES
    return max(4096, min(limit, 16 * 1024 * 1024))

# --- SyncEngine (System C: fast catch-up) ---
try:
    from sync.sync_engine import SyncEngine
    _SYNC_ENGINE_AVAILABLE = True
except ImportError:
    _SYNC_ENGINE_AVAILABLE = False

# ── Типы сообщений ────────────────────────────────────────────────────────────

MSG_HANDSHAKE  = "handshake"
MSG_HANDSHAKE_ACK = "handshake_ack"
MSG_PING       = "ping"
MSG_PONG       = "pong"
MSG_IDLE       = "__idle__"
MSG_NEW_BLOCK  = "new_block"
MSG_GET_BLOCK  = "get_block"
MSG_GET_BLOCK_BY_HASH = "get_block_by_hash"
MSG_BLOCK      = "block"
MSG_GET_BLOCKS = "get_blocks"   # диапазон блоков
MSG_BLOCKS     = "blocks"
MSG_NEW_TX     = "new_tx"
MSG_GET_MEMPOOL = "get_mempool"
MSG_MEMPOOL    = "mempool"
MSG_GET_PEERS  = "get_peers"
MSG_PEERS      = "peers"
MSG_STATUS     = "status"       # height + head hash
MSG_ATTESTATION = "attestation"
MSG_STATE_ROOT_REQUEST = "state_root_request"
MSG_STATE_ROOT_RESPONSE = "state_root_response"
MSG_VALIDATOR_REGISTER = "validator_register"
MSG_CROSS_SHARD_TX = "cross_shard_tx"
MSG_CROSS_SHARD_ACK = "cross_shard_ack"
MSG_SHARD_MIGRATION = "shard_migration"

ALLOWED_WIRE_TYPES = frozenset({
    MSG_HANDSHAKE,
    MSG_HANDSHAKE_ACK,
    MSG_PING,
    MSG_PONG,
    MSG_IDLE,
    MSG_NEW_BLOCK,
    MSG_GET_BLOCK,
    MSG_GET_BLOCK_BY_HASH,
    MSG_BLOCK,
    MSG_GET_BLOCKS,
    MSG_BLOCKS,
    MSG_NEW_TX,
    MSG_GET_MEMPOOL,
    MSG_MEMPOOL,
    MSG_GET_PEERS,
    MSG_PEERS,
    MSG_STATUS,
    MSG_ATTESTATION,
    MSG_STATE_ROOT_REQUEST,
    MSG_STATE_ROOT_RESPONSE,
    MSG_VALIDATOR_REGISTER,
    MSG_CROSS_SHARD_TX,
    MSG_CROSS_SHARD_ACK,
    MSG_SHARD_MIGRATION,
})

# Housekeeping + consensus/sync wire types are not counted toward per-peer rate limits.
# v1.3.143: MSG_NEW_TX is NOT exempt — gossip hits the primary rate budget so tx spam
# cannot hide behind the sync/exempt ceiling. Soft DoS honesty only — not anti-Sybil.
RATE_LIMIT_EXEMPT_TYPES = frozenset({
    MSG_PING,
    MSG_PONG,
    MSG_IDLE,
    MSG_STATUS,
    MSG_STATE_ROOT_REQUEST,
    MSG_STATE_ROOT_RESPONSE,
    MSG_NEW_BLOCK,
    MSG_GET_BLOCK,
    MSG_GET_BLOCK_BY_HASH,
    MSG_GET_BLOCKS,
    MSG_BLOCK,
    MSG_BLOCKS,
    MSG_GET_MEMPOOL,
    MSG_MEMPOOL,
})

# Per-peer class quotas on top of primary/exempt budgets. One flood class must
# not monopolize the shared 500/s (or exempt 2000/s) window. 0 on config = off.
RATE_LIMIT_CLASS_ATTEST = "attest"
RATE_LIMIT_CLASS_TX = "tx"
RATE_LIMIT_CLASS_BLOCK = "block_announce"


def _housekeeping_payload_ok(msg_type: str, data: Any) -> bool:
    """Fail-closed payload rules for rate-exempt housekeeping messages."""
    if data is None:
        return True
    if msg_type in (MSG_PING, MSG_PONG):
        if not isinstance(data, dict):
            return False
        if not data:
            return True
        if set(data.keys()) <= {"ts"} and isinstance(data.get("ts"), (int, float)):
            return True
        return False
    if msg_type in (MSG_GET_MEMPOOL, MSG_GET_PEERS):
        return isinstance(data, dict) and len(data) == 0
    return False


def _clamp_native_batch(n: Any, default: int = 8) -> int:
    """v1.3.101: clamp read/write batch size to Rust bounds (1..64)."""
    try:
        raw = int(n if n is not None else default)
    except (TypeError, ValueError):
        raw = int(default)
    if hasattr(native, "p2p_native_clamp_batch"):
        try:
            return int(native.p2p_native_clamp_batch(max(0, raw)))
        except Exception as exc:
            logger.warning(
                "[P2P] native p2p_native_clamp_batch failed; Python clamp: %s", exc
            )
    return max(1, min(64, raw if raw > 0 else default))


def _clamp_native_chunk(n: Any, default: int = 65536) -> int:
    """v1.3.101: clamp native read chunk (1024..1MiB)."""
    try:
        raw = int(n if n is not None else default)
    except (TypeError, ValueError):
        raw = int(default)
    if hasattr(native, "p2p_native_clamp_chunk"):
        try:
            return int(native.p2p_native_clamp_chunk(max(0, raw)))
        except Exception as exc:
            logger.warning(
                "[P2P] native p2p_native_clamp_chunk failed; Python clamp: %s", exc
            )
    return max(1024, min(1024 * 1024, raw if raw > 0 else default))


def _clamp_native_timeout_ms(n: Any, default: int = 30000) -> int:
    """v1.3.102: clamp native socket I/O timeout (1000..600000 ms)."""
    try:
        raw = int(n if n is not None else default)
    except (TypeError, ValueError):
        raw = int(default)
    if hasattr(native, "p2p_native_clamp_timeout_ms"):
        try:
            return int(native.p2p_native_clamp_timeout_ms(max(0, raw)))
        except Exception as exc:
            logger.warning(
                "[P2P] native p2p_native_clamp_timeout_ms failed; Python clamp: %s",
                exc,
            )
    return max(1000, min(600_000, raw if raw > 0 else default))


# Soft peer score lives in network.peer_manager (imported as _peer_health_score).


class PeerConnection:
    """Активное соединение с одним пиром."""

    def __init__(
        self,
        reader: Optional[asyncio.StreamReader] = None,
        writer: Optional[asyncio.StreamWriter] = None,
        peer_id: str = "",
        *,
        send_queue_max: int = 256,
        drain_timeout_sec: float = 5.0,
        native_conn=None,
        libp2p_adapter=None,
        libp2p_peer_id: str = "",
    ):
        self._native_conn = native_conn  # optional P2PNativeConn (v1.3.90)
        self._libp2p_adapter = libp2p_adapter
        self._libp2p_peer_id = str(libp2p_peer_id or "")
        self._libp2p_inbound: Optional[asyncio.Queue] = (
            asyncio.Queue(maxsize=max(32, int(send_queue_max or 256)))
            if libp2p_adapter is not None
            else None
        )
        self._message_loop_owns_writes = False
        self._in_message_loop_task = False
        self.reader = reader
        self.writer = writer
        self.peer_id = peer_id
        if native_conn is not None:
            self.host = str(getattr(native_conn, "peer_host", "") or "")
            self.port = int(getattr(native_conn, "peer_port", 0) or 0)
        elif writer is not None:
            self.host = writer.get_extra_info("peername", ("?", 0))[0]
            self.port = 0
        else:
            self.host = "?"
            self.port = 0
        self.listen_port = 0
        self.chain_id: int = 0
        self.height: int = 0
        self.head: Optional[str] = None  # head block hash for SyncEngine/GHOST
        self.dial_target = ""  # v1.3.132: outbound "host:port" as dialed
        self.connected_at = time.time()
        self.last_seen = time.time()
        self.is_synced = False
        # v1.3.145: session quality counters for peer score / eclipse prune
        self.quality_import_fails: int = 0
        self.tls_fingerprint = ""
        self.tls_identities: list = []
        self._on_send_fail: Optional[Callable[[], None]] = None
        self._on_send_drop: Optional[Callable[[], None]] = None
        self._on_egress_reject: Optional[Callable[[], None]] = None
        self._rl_table = None  # optional native P2PRateLimitTable (egress v1.3.85)
        # Shared across peers: serialize PyRefMut on the one RateLimitTable (thread pool).
        self._rl_lock: Optional[threading.RLock] = None
        # Per-connection: native P2PNativeConn is !Sync RefCell — no concurrent read/write.
        self._native_io_lock = threading.RLock()
        self._line_framer = None  # optional native P2PLineFramer (v1.3.86)
        self._pending_lines: list = []
        self._pending_msgs: list = []  # v1.3.94 decoded batch from read_messages
        self._pending_loop_events: list = []  # v1.3.116 shell events
        self._native_read_batch: int = 8
        self._native_message_loop_shell: bool = False
        self._native_write_batch: int = 8
        self._native_auto_pong: bool = True
        self._native_io_timeout_ms: int = 30000
        self._native_poll_timeout_ms: int = 100
        self._use_egress_prepare = False  # v1.3.87 unified prepare
        self._transport_adapter = None  # set by P2PNode._attach_peer_hooks (Step C)
        self._wire_codec = None  # ADR 0008: learned peer codec (v1|v2); None → auto
        self._egress_max_bytes = DEFAULT_MAX_P2P_LINE_BYTES
        # v1.3.66/72: bounded outbound queue (config-driven size + drain timeout)
        qmax = max(8, int(send_queue_max or 256))
        self._send_q: asyncio.Queue = asyncio.Queue(maxsize=qmax)
        # Control-plane / solicit: own queue so gossip cannot HOL, and so the
        # caller never takes _send_io_lock (that starved recv + HTTP → prune).
        self._send_ctrl_q: asyncio.Queue = asyncio.Queue(maxsize=max(32, qmax))
        # state_root must jump BLOCK/STATUS on the ctrl queue — those frames
        # held `_native_io_lock` long enough that the 2s send Future timed out
        # and cancelled the solicit waiter while the request was still queued.
        self._send_root_q: asyncio.Queue = asyncio.Queue(maxsize=max(32, qmax))
        self._send_wake: Optional[asyncio.Event] = None
        self._send_worker: Optional[asyncio.Task] = None
        # Serializes native/TCP writes inside the send worker only.
        self._send_io_lock: Optional[asyncio.Lock] = None
        self._send_drops: int = 0
        self._drain_timeout_sec: float = max(0.5, float(drain_timeout_sec or 5.0))
        self._read_chunk: int = 65536

    def _native_recv_wait_sec(self) -> float:
        """Async wait bound matching socket I/O timeout (+1s cushion)."""
        ms = int(getattr(self, "_native_io_timeout_ms", 30000) or 30000)
        return max(2.0, (ms / 1000.0) + 1.0)

    def _native_poll_wait_sec(self) -> float:
        """Outer asyncio bound for a single non-blocking native poll."""
        ms = int(getattr(self, "_native_poll_timeout_ms", 100) or 100)
        return max(0.5, (ms / 1000.0) + 0.4)

    def _native_io_call(self, method, *args, **kwargs):
        """Run a native-conn method under the per-connection IO lock."""
        lock = getattr(self, "_native_io_lock", None)
        if lock is None:
            return method(*args, **kwargs)
        with lock:
            return method(*args, **kwargs)

    def _native_poll_read_call(self, method, *args, **kwargs):
        """Native read under IO lock with a short SO_RCVTIMEO so writers are not starved.

        Holding ``_native_io_lock`` across a 30s blocking read deadlocks solicit
        responses (get_block / state_root) that need the same RefCell/conn.
        """
        lock = getattr(self, "_native_io_lock", None)
        conn = getattr(self, "_native_conn", None)
        poll_ms = max(1, int(getattr(self, "_native_poll_timeout_ms", 100) or 100))
        full_ms = max(1, int(getattr(self, "_native_io_timeout_ms", 30000) or 30000))

        def _run():
            restored = False
            if conn is not None:
                if hasattr(conn, "set_read_timeout_ms"):
                    try:
                        conn.set_read_timeout_ms(poll_ms)
                        restored = True
                    except Exception as exc:
                        logger.debug(
                            "[P2P] set_read_timeout_ms poll failed: %s", exc
                        )
                        restored = False
                elif hasattr(conn, "set_timeout_ms"):
                    try:
                        conn.set_timeout_ms(poll_ms)
                        restored = True
                    except Exception as exc:
                        logger.debug("[P2P] set_timeout_ms poll failed: %s", exc)
                        restored = False
            try:
                return method(*args, **kwargs)
            finally:
                if restored and conn is not None:
                    try:
                        if hasattr(conn, "set_read_timeout_ms"):
                            # Restore read side; write timeout left at full via set_timeout_ms.
                            conn.set_timeout_ms(full_ms)
                        elif hasattr(conn, "set_timeout_ms"):
                            conn.set_timeout_ms(full_ms)
                    except Exception as exc:
                        logger.debug("[P2P] restore native timeout failed: %s", exc)

        if lock is None:
            return _run()
        with lock:
            return _run()

    def _effective_wire_codec(self) -> str:
        """Concrete outbound codec for this peer (auto → learned / v1 bootstrap).

        Never touch ``_native_conn`` here: prepare runs off the IO lock and would
        race PyO3 borrows against ``read_messages`` / ``write`` (Already mutably
        borrowed → mesh wire_probe FAIL).
        """
        learned = getattr(self, "_wire_codec", None)
        if learned in ("v1", "v2"):
            return str(learned)
        mode = native.p2p_wire_codec_mode()
        if mode in ("v1", "v2"):
            return mode
        return "v1"

    def _note_peer_wire_codec(self, codec: Any) -> None:
        """Remember peer's inbound codec and sync native conn for auto replies."""
        raw = str(codec or "").strip().lower()
        if raw not in ("v1", "v2"):
            return
        self._wire_codec = raw
        conn = getattr(self, "_native_conn", None)
        if conn is not None and hasattr(conn, "set_peer_wire_codec"):
            try:
                self._native_io_call(conn.set_peer_wire_codec, raw)
            except Exception as exc:
                logger.warning("[P2P] set_peer_wire_codec failed: %s", exc)

    def touch(self):
        self.last_seen = time.time()

    def _rl_call(self, fn, *args, **kwargs):
        """Run rate-limit / egress-prepare against the shared table under lock."""
        lock = getattr(self, "_rl_lock", None)
        if lock is None:
            return fn(*args, **kwargs)
        with lock:
            return fn(*args, **kwargs)

    def _native_write_timeout_sec(self) -> float:
        """Bound a native/TCP write so `_native_io_lock` cannot starve recv.

        A 30s write hold deadlocks both sides: we cannot read, the peer's
        send buffer fills, their write also blocks. Probe budget is 6.5s.
        """
        return max(0.4, min(0.75, float(self._drain_timeout_sec or 5.0)))

    def _native_write_bound(self, fn, *args):
        """Set SO_SNDTIMEO then invoke `fn`. Caller must hold `_native_io_lock`.

        asyncio.wait_for cannot cancel a native write thread. Without a socket
        timeout the thread keeps the IO lock for 30s after wait_for fires,
        and state_root sits behind a deadlocked TCP window.
        """
        conn = self._native_conn
        ms = max(1, int(self._native_write_timeout_sec() * 1000))
        if conn is not None and hasattr(conn, "set_timeout_ms"):
            try:
                conn.set_timeout_ms(ms)
            except Exception as exc:
                logger.debug("[P2P] set_timeout_ms failed: %s", exc)
        return fn(*args)

    async def _write_payload(self, payload: bytes) -> None:
        """Write framed bytes via native TCP conn or asyncio writer."""
        write_timeout = self._native_write_timeout_sec()
        if self._native_conn is not None:
            await asyncio.wait_for(
                asyncio.to_thread(
                    self._native_io_call,
                    self._native_write_bound,
                    self._native_conn.write,
                    payload,
                ),
                timeout=write_timeout + 0.5,
            )
            return
        if self.writer is None:
            raise OSError("p2p_no_writer")
        self.writer.write(payload)
        await asyncio.wait_for(self.writer.drain(), timeout=write_timeout)

    async def _write_message(self, msg_type: str, data: Any) -> bool:
        """v1.3.93: native encode+write pump, or prepare+write when egress on."""
        libp2p_ad = getattr(self, "_libp2p_adapter", None)
        libp2p_pid = str(getattr(self, "_libp2p_peer_id", "") or "").strip()
        if libp2p_ad is not None and libp2p_pid:
            from network.transport.errors import TransportValidationError

            codec = self._effective_wire_codec()
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        libp2p_ad.send_abs_wire,
                        libp2p_pid,
                        str(msg_type),
                        data,
                        codec=codec,
                    ),
                    timeout=self._native_write_timeout_sec() + 0.5,
                )
                return True
            except TransportValidationError as exc:
                logger.warning(
                    "[P2P] libp2p abs wire prepare refused to %s: %s",
                    self.peer_id or libp2p_pid,
                    exc,
                )
                self._invoke_peer_hook(self._on_egress_reject, name="egress_reject")
                return False
            except Exception as exc:
                logger.warning(
                    "[P2P] libp2p send_abs_wire failed to %s: %s",
                    self.peer_id or libp2p_pid,
                    exc,
                )
                self._invoke_peer_hook(self._on_send_fail, name="send_fail")
                return False
        if (
            self._native_conn is not None
            and hasattr(self._native_conn, "write_message")
        ):
            # Egress prepare already encodes + admits on the main thread.
            if self._use_egress_prepare and hasattr(native, "p2p_egress_prepare"):
                payload = self._prepare_outbound(msg_type, data)
                if payload is None:
                    return False
                await self._write_payload(payload)
                return True
            # Legacy egress gate needs payload size before write — keep prepare/encode path.
            if self._rl_table is not None and hasattr(self._rl_table, "admit_egress"):
                payload = self._prepare_outbound(msg_type, data)
                if payload is None:
                    return False
                await self._write_payload(payload)
                return True
            import json

            data_json = (
                "null"
                if data is None
                else json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            )
            out = await asyncio.wait_for(
                asyncio.to_thread(
                    self._native_io_call,
                    self._native_write_bound,
                    self._native_conn.write_message,
                    str(msg_type or ""),
                    data_json,
                    list(ALLOWED_WIRE_TYPES),
                    "auto",
                ),
                timeout=self._native_write_timeout_sec() + 0.5,
            )
            if not isinstance(out, dict) or not out.get("ok"):
                reason = ""
                if isinstance(out, dict):
                    reason = str(out.get("reason") or "")
                logger.warning(
                    "[P2P] write_message reject to %s (%s)",
                    self.peer_id or self.host,
                    reason or "write_failed",
                )
                return False
            return True
        payload = self._prepare_outbound(msg_type, data)
        if payload is None:
            return False
        await self._write_payload(payload)
        return True

    async def _write_messages_batch(self, batch: list) -> list:
        """v1.3.95: send multiple queued envelopes in one native hop when possible.

        `batch` is a list of (msg_type, data, fut). Returns list of bool results.
        """
        if not batch:
            return []
        libp2p_ad = getattr(self, "_libp2p_adapter", None)
        libp2p_pid = str(getattr(self, "_libp2p_peer_id", "") or "").strip()
        if libp2p_ad is not None and libp2p_pid:
            return [await self._write_message(msg_type, data) for msg_type, data, _fut in batch]
        if len(batch) == 1:
            msg_type, data, _fut = batch[0]
            return [await self._write_message(msg_type, data)]

        use_native = self._native_conn is not None
        # Egress-prepare path: admit/encode on main thread, then write_payloads.
        if (
            use_native
            and hasattr(self._native_conn, "write_payloads")
            and (
                (self._use_egress_prepare and hasattr(native, "p2p_egress_prepare"))
                or (
                    self._rl_table is not None
                    and hasattr(self._rl_table, "admit_egress")
                )
            )
        ):
            payloads: list = []
            results = [False] * len(batch)
            for i, (msg_type, data, _fut) in enumerate(batch):
                payload = self._prepare_outbound(msg_type, data)
                if payload is None:
                    results[i] = False
                else:
                    payloads.append((i, payload))
            if payloads:
                out = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._native_io_call,
                        self._native_write_bound,
                        self._native_conn.write_payloads,
                        [p for _i, p in payloads],
                    ),
                    timeout=self._native_write_timeout_sec() + 0.5,
                )
                ok = isinstance(out, dict) and bool(out.get("ok"))
                written = int(out.get("written") or out.get("count") or 0) if isinstance(out, dict) else 0
                if ok:
                    for i, _p in payloads:
                        results[i] = True
                else:
                    for n, (i, _p) in enumerate(payloads):
                        results[i] = n < written
                    logger.warning(
                        "[P2P] write_payloads reject to %s (%s)",
                        self.peer_id or self.host,
                        (out or {}).get("reason") if isinstance(out, dict) else "write_failed",
                    )
            return results

        # Pure encode+write batch (no egress table).
        if use_native and hasattr(self._native_conn, "write_messages"):
            import json

            items = []
            for msg_type, data, _fut in batch:
                data_json = (
                    "null"
                    if data is None
                    else json.dumps(data, separators=(",", ":"), ensure_ascii=False)
                )
                items.append((str(msg_type or ""), data_json))
            out = await asyncio.wait_for(
                asyncio.to_thread(
                    self._native_io_call,
                    self._native_write_bound,
                    self._native_conn.write_messages,
                    items,
                    list(ALLOWED_WIRE_TYPES),
                ),
                timeout=self._native_write_timeout_sec() + 0.5,
            )
            if isinstance(out, dict) and out.get("ok"):
                return [True] * len(batch)
            written = int(out.get("written") or 0) if isinstance(out, dict) else 0
            logger.warning(
                "[P2P] write_messages reject to %s (%s)",
                self.peer_id or self.host,
                (out or {}).get("reason") if isinstance(out, dict) else "write_failed",
            )
            return [i < written for i in range(len(batch))]

        # Fallback: one-by-one.
        results = []
        for msg_type, data, _fut in batch:
            results.append(await self._write_message(msg_type, data))
        return results

    def _egress_peer_key(self) -> str:
        if self.peer_id:
            return str(self.peer_id)
        if self.port:
            return f"{self.host}:{self.port}"
        return str(self.host or "unknown")

    def _invoke_peer_hook(self, cb: Optional[Callable[[], None]], *, name: str) -> None:
        """Run send/drop/egress counters without letting a hook abort the wire path."""
        if cb is None:
            return
        try:
            cb()
        except Exception as exc:
            logger.warning(
                "[P2P] %s hook failed to %s: %s",
                name,
                self.peer_id or self.host,
                exc,
            )

    def _egress_ok(self, msg_type: str, payload: bytes) -> bool:
        """v1.3.85: cost-weighted outbound bandwidth gate (fail-closed drop)."""
        table = self._rl_table
        if table is None or not hasattr(table, "admit_egress"):
            return True

        def _admit():
            return table.admit_egress(
                self._egress_peer_key(),
                len(payload),
                time.time(),
                str(msg_type or ""),
            )

        reason = self._rl_call(_admit)
        if reason:
            self._invoke_peer_hook(self._on_egress_reject, name="egress_reject")
            return False
        return True

    def _prepare_outbound(self, msg_type: str, data: Any) -> Optional[bytes]:
        """v1.3.87: encode + allowlist + size + egress admit (or legacy fallback)."""
        return self._rl_call(self._prepare_outbound_unlocked, msg_type, data)

    def _prepare_outbound_unlocked(self, msg_type: str, data: Any) -> Optional[bytes]:
        """Inner prepare; caller must hold ``_rl_lock`` when shared table is used."""
        adapter = getattr(self, "_transport_adapter", None)
        if self._use_egress_prepare and (
            adapter is not None or hasattr(native, "p2p_egress_prepare")
        ):
            data_json = (
                "null"
                if data is None
                else json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            )
            peer_key = self._egress_peer_key()
            max_bytes = int(self._egress_max_bytes or DEFAULT_MAX_P2P_LINE_BYTES)
            try:
                if adapter is not None:
                    from network.transport import OutboundEnvelope

                    decision = adapter.prepare_outbound(
                        OutboundEnvelope(
                            peer_id=str(peer_key or ""),
                            msg_type=str(msg_type or ""),
                            payload={},
                        ),
                        now=float(time.time()),
                        max_bytes=max_bytes,
                        allowed_types=list(ALLOWED_WIRE_TYPES),
                        rate_table=self._rl_table,
                        data_json=data_json,
                        peer_wire_codec=self._effective_wire_codec(),
                    )
                    if not decision.accepted:
                        reason = (
                            decision.reject.reason_code
                            if decision.reject is not None
                            else "prepare_failed"
                        )
                        if "egress_bandwidth" in reason:
                            self._invoke_peer_hook(
                                self._on_egress_reject, name="egress_reject"
                            )
                        else:
                            logger.warning(
                                "[P2P] egress prepare reject to %s (%s)",
                                self.peer_id or self.host,
                                reason or "prepare_failed",
                            )
                        return None
                    payload = (decision.frame.data or {}).get("payload") if decision.frame else None
                    return bytes(payload or b"")
                out = native.p2p_egress_prepare(
                    str(msg_type or ""),
                    data_json,
                    peer_key,
                    float(time.time()),
                    max_bytes,
                    list(ALLOWED_WIRE_TYPES),
                    self._rl_table,
                    self._effective_wire_codec(),
                )
            except Exception as exc:
                logger.warning(
                    "[P2P] egress prepare error to %s: %s",
                    self.peer_id or self.host,
                    exc,
                )
                return None
            if not isinstance(out, dict) or not out.get("ok"):
                reason = ""
                if isinstance(out, dict):
                    reason = str(out.get("reason") or "")
                if "egress_bandwidth" in reason:
                    self._invoke_peer_hook(self._on_egress_reject, name="egress_reject")
                else:
                    logger.warning(
                        "[P2P] egress prepare reject to %s (%s)",
                        self.peer_id or self.host,
                        reason or "prepare_failed",
                    )
                return None
            return bytes(out.get("payload") or b"")
        payload = native.encode_p2p_wire_message_codec(
            msg_type,
            data,
            codec=self._effective_wire_codec(),
        )
        if not self._egress_ok(msg_type, payload):
            return None
        return payload

    def _ensure_send_worker(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._send_io_lock is None:
            self._send_io_lock = asyncio.Lock()
        if self._send_wake is None:
            self._send_wake = asyncio.Event()
        if self._send_worker is not None and not self._send_worker.done():
            return
        self._send_worker = loop.create_task(self._send_loop())

    def _wake_send(self) -> None:
        ev = self._send_wake
        if ev is not None and not ev.is_set():
            ev.set()

    def _outbound_queues(self):
        """state_root, then ctrl (status/blocks), then gossip."""
        return (self._send_root_q, self._send_ctrl_q, self._send_q)

    async def _next_outbound(self):
        """Prefer state_root, then ctrl; never block the caller on the write lock."""
        while True:
            for q in self._outbound_queues():
                try:
                    return q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            if self._send_wake is None:
                self._send_wake = asyncio.Event()
            self._send_wake.clear()
            for q in self._outbound_queues():
                try:
                    return q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await self._send_wake.wait()

    async def _send_loop(self) -> None:
        while True:
            try:
                item = await self._next_outbound()
            except asyncio.CancelledError:
                break
            if item is None:
                break
            batch = [item]
            # v1.3.95: drain additional pending items for one native write hop.
            max_batch = max(1, int(getattr(self, "_native_write_batch", 8) or 8))
            first_type = str(batch[0][0] or "") if batch else ""
            root_types = {MSG_STATE_ROOT_REQUEST, MSG_STATE_ROOT_RESPONSE}
            root_waiting = False
            try:
                root_waiting = not self._send_root_q.empty()
            except Exception as exc:
                logger.debug("[P2P] send_root_q.empty probe failed: %s", exc)
                root_waiting = False
            # Singleton flush for state_root; yield if a root frame is waiting
            # so BLOCK/STATUS cannot HOL the probe inside write_payloads.
            if first_type not in root_types and not root_waiting:
                while len(batch) < max_batch:
                    nxt = None
                    try:
                        nxt = self._send_ctrl_q.get_nowait()
                    except asyncio.QueueEmpty:
                        try:
                            nxt = self._send_q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    if nxt is None:
                        try:
                            self._send_ctrl_q.put_nowait(None)
                        except asyncio.QueueFull:
                            pass
                        self._wake_send()
                        break
                    batch.append(nxt)
            lock = self._send_io_lock
            try:
                if lock is not None:
                    async with lock:
                        results = await self._write_messages_batch(batch)
                else:
                    results = await self._write_messages_batch(batch)
            except asyncio.TimeoutError:
                logger.warning(
                    "[P2P] send timeout to %s (batch=%s)",
                    self.peer_id or self.host,
                    len(batch),
                )
                self._invoke_peer_hook(self._on_send_fail, name="send_fail")
                results = [False] * len(batch)
                root_types = {MSG_STATE_ROOT_REQUEST, MSG_STATE_ROOT_RESPONSE}
                for item in batch:
                    msg_type = str(item[0] or "") if item else ""
                    tries = int(item[3]) if item is not None and len(item) > 3 else 0
                    if msg_type in root_types and tries < 2:
                        try:
                            self._send_root_q.put_nowait(
                                (item[0], item[1], item[2], tries + 1)
                            )
                            self._wake_send()
                        except asyncio.QueueFull:
                            pass
            except Exception as e:
                logger.warning(
                    "[P2P] send error to %s: %s",
                    self.peer_id or self.host,
                    e or type(e).__name__,
                )
                self._invoke_peer_hook(self._on_send_fail, name="send_fail")
                results = [False] * len(batch)
            for item, ok in zip(batch, results):
                fut = item[2] if item is not None and len(item) > 2 else None
                if fut is not None and not fut.done():
                    fut.set_result(bool(ok))

    async def send(self, msg_type: str, data: Any = None, *, wait: bool = False) -> bool:
        """Enqueue a frame. Returns False on queue full, or on write fail if wait=True.

        Default wait=False: the message loop must not await the write Future.
        Awaiting send() while the worker holds ``_native_io_lock`` stopped recv
        and stuck both TCP windows (empty wire probe). Handshake/reconnect pass
        wait=True when they need the write result.
        """
        self._ensure_send_worker()
        kind = str(msg_type or "")
        if kind in (MSG_STATE_ROOT_REQUEST, MSG_STATE_ROOT_RESPONSE):
            q = self._send_root_q
            drop_cb = False
        elif kind in {
            MSG_STATUS,
            MSG_PING,
            MSG_PONG,
            MSG_HANDSHAKE,
            MSG_HANDSHAKE_ACK,
            MSG_GET_BLOCK,
            MSG_GET_BLOCK_BY_HASH,
            MSG_GET_BLOCKS,
            MSG_GET_PEERS,
            MSG_PEERS,
            MSG_BLOCK,
            MSG_BLOCKS,
        }:
            q = self._send_ctrl_q
            drop_cb = False
        else:
            q = self._send_q
            drop_cb = True
        fut = None
        if wait:
            fut = asyncio.get_running_loop().create_future()
        try:
            q.put_nowait((msg_type, data, fut))
        except asyncio.QueueFull:
            self._send_drops += 1
            if drop_cb:
                self._invoke_peer_hook(self._on_send_drop, name="send_drop")
            else:
                logger.warning(
                    "[P2P] send queue full to %s type=%s",
                    self.peer_id or self.host,
                    msg_type,
                )
            return False
        except Exception as e:
            logger.warning("[P2P] send enqueue error to %s: %s", self.peer_id or self.host, e)
            return False
        self._wake_send()
        # state_root enqueue does not wait the write Future — the solicit
        # waiter owns the RTT. Waiting 2s here aborted the waiter while the
        # frame was still queued, so replies landed unsolicited/empty.
        if not wait or fut is None:
            return True
        send_wait = float(self._drain_timeout_sec or 5.0) + 1.0
        try:
            return bool(await asyncio.wait_for(fut, timeout=send_wait))
        except asyncio.TimeoutError:
            logger.warning(
                "[P2P] send timeout to %s type=%s",
                self.peer_id or self.host,
                msg_type,
            )
            return False
        except Exception as e:
            logger.warning(
                "[P2P] send error to %s: %s",
                self.peer_id or self.host,
                e or type(e).__name__,
            )
            return False
        self._ensure_send_worker()
        kind = str(msg_type or "")
        if kind in (MSG_STATE_ROOT_REQUEST, MSG_STATE_ROOT_RESPONSE):
            q = self._send_root_q
            drop_cb = False
        elif kind in {
            MSG_STATUS,
            MSG_PING,
            MSG_PONG,
            MSG_HANDSHAKE,
            MSG_HANDSHAKE_ACK,
            MSG_GET_BLOCK,
            MSG_GET_BLOCK_BY_HASH,
            MSG_GET_BLOCKS,
            MSG_GET_PEERS,
            MSG_PEERS,
            MSG_BLOCK,
            MSG_BLOCKS,
        }:
            q = self._send_ctrl_q
            drop_cb = False
        else:
            q = self._send_q
            drop_cb = True
        try:
            q.put_nowait((msg_type, data, None))
        except asyncio.QueueFull:
            self._send_drops += 1
            if drop_cb:
                self._invoke_peer_hook(self._on_send_drop, name="send_drop")
            else:
                logger.warning(
                    "[P2P] send queue full to %s type=%s",
                    self.peer_id or self.host,
                    msg_type,
                )
            return False
        except Exception as e:
            logger.warning("[P2P] send enqueue error to %s: %s", self.peer_id or self.host, e)
            return False
        self._wake_send()
        # state_root enqueue does not wait the write Future — the solicit
        # waiter owns the RTT. Waiting 2s here aborted the waiter while the
        # frame was still queued, so replies landed unsolicited/empty.
        return True

    async def _read_wire_line(self, limit: int):
        """Read one NDJSON line via native framer when available (v1.3.86).

        Falls back to asyncio readline. Returns bytes | None (EOF).
        Raises ValueError with reason p2p_line_too_large on oversize.
        v1.3.90: optional P2PNativeConn owns TCP + framer in Rust.
        """
        if self._pending_lines:
            return self._pending_lines.pop(0)

        if self._native_conn is not None:
            out = await asyncio.wait_for(
                asyncio.to_thread(
                    self._native_io_call,
                    self._native_conn.read_line,
                    int(self._read_chunk or 65536),
                ),
                timeout=30,
            )
            if not isinstance(out, dict) or not out.get("ok"):
                reason = "p2p_line_too_large"
                if isinstance(out, dict):
                    reason = str(out.get("reason") or reason)
                if reason == "p2p_transport_timeout":
                    raise asyncio.TimeoutError()
                raise ValueError(reason)
            if out.get("eof") or out.get("line") is None:
                return None
            line = out.get("line")
            return bytes(line) if not isinstance(line, (bytes, bytearray)) else bytes(line)

        if self._line_framer is None and hasattr(native, "P2PLineFramer"):
            try:
                self._line_framer = native.P2PLineFramer(int(limit))
            except Exception as exc:
                logger.warning(
                    "[P2P] P2PLineFramer construct failed; Python readline fallback: %s",
                    exc,
                )
                self._line_framer = None

        framer = self._line_framer
        if framer is None:
            if self.reader is None:
                return None
            return await asyncio.wait_for(self.reader.readline(), timeout=30)

        chunk_sz = max(1024, int(self._read_chunk or 65536))
        while True:
            if self.reader is None:
                return None
            chunk = await asyncio.wait_for(self.reader.read(chunk_sz), timeout=30)
            if not chunk:
                # EOF with incomplete pending → treat as closed (no silent partial envelope).
                if int(getattr(framer, "pending_len", 0) or 0) > 0:
                    framer.clear()
                    raise ValueError("p2p_line_incomplete")
                return None
            fed = framer.feed(chunk)
            if not isinstance(fed, dict) or not fed.get("ok"):
                reason = "p2p_line_too_large"
                if isinstance(fed, dict):
                    reason = str(fed.get("reason") or reason)
                raise ValueError(reason)
            lines = list(fed.get("lines") or [])
            if lines:
                self._pending_lines.extend(lines[1:])
                return lines[0]

    def _admit_pending_item(
        self,
        item: dict,
        *,
        use_ingress: bool = False,
        rl_table=None,
        peer_key: str = "",
    ):
        """Apply optional ingress rate admit to a decoded native batch item."""
        msg_type = item.get("type")
        data = item.get("data")
        nbytes = int(item.get("nbytes") or 0)
        self._note_peer_wire_codec(item.get("wire_codec"))
        if use_ingress and rl_table is not None and hasattr(rl_table, "admit_rate"):
            def _admit():
                return rl_table.admit_rate(
                    str(peer_key or self.peer_id or self.host or ""),
                    str(msg_type or ""),
                    float(time.time()),
                    int(nbytes),
                )

            reject = self._rl_call(_admit)
            if reject:
                reason = str(reject)
                logger.warning(
                    "[P2P] ingress rate reject from %s (%s)",
                    self.peer_id or self.host,
                    reason,
                )
                return WireReject(reason)
        return {"type": msg_type, "data": data}

    async def recv_loop_events(
        self,
        config=None,
        *,
        rl_table=None,
        peer_key: str = "",
        use_ingress: bool = False,
        mempool_solicit_armed: bool = False,
    ) -> list:
        """v1.3.116: drain native ordered loop-shell events (dispatch/strike/…).

        Returns a list of event dicts. Empty list means idle/timeout with no work.
        Application dispatch and strike policy remain in P2PNode._message_loop.

        v1.3.144: mempool_solicit_armed — when False, native shell refuses MSG_MEMPOOL
        before batch ECDSA (unsolicited_mempool). Soft DoS honesty only.
        """
        if self._pending_loop_events:
            return [self._pending_loop_events.pop(0)]
        if self._native_conn is None or not hasattr(
            self._native_conn, "read_message_loop_events"
        ):
            return []
        chain_id = int(getattr(config, "chain_id", 0) or 0) if config is not None else 0
        require_sigs = bool(getattr(config, "require_signatures", False)) if config is not None else False
        poll_ms = max(1, int(getattr(self, "_native_poll_timeout_ms", 100) or 100))
        supports_poll = getattr(self, "_native_loop_poll_arg", None)
        if supports_poll is None:
            supports_poll = False
            try:
                import inspect

                supports_poll = (
                    "poll_timeout_ms"
                    in inspect.signature(self._native_conn.read_message_loop_events).parameters
                )
            except Exception as exc:
                logger.debug(
                    "[P2P] native loop poll_timeout_ms probe failed: %s", exc
                )
                supports_poll = False
            self._native_loop_poll_arg = supports_poll
        if supports_poll:
            out = await asyncio.wait_for(
                asyncio.to_thread(
                    self._native_io_call,
                    self._native_conn.read_message_loop_events,
                    int(self._native_read_batch or 8),
                    int(self._read_chunk or 65536),
                    list(ALLOWED_WIRE_TYPES),
                    bool(getattr(self, "_native_auto_pong", True)),
                    int(chain_id) if chain_id else None,
                    bool(require_sigs),
                    bool(mempool_solicit_armed),
                    poll_ms,
                ),
                timeout=self._native_poll_wait_sec(),
            )
        else:
            out = await asyncio.wait_for(
                asyncio.to_thread(
                    self._native_poll_read_call,
                    self._native_conn.read_message_loop_events,
                    int(self._native_read_batch or 8),
                    int(self._read_chunk or 65536),
                    list(ALLOWED_WIRE_TYPES),
                    bool(getattr(self, "_native_auto_pong", True)),
                    int(chain_id) if chain_id else None,
                    bool(require_sigs),
                    bool(mempool_solicit_armed),
                ),
                timeout=self._native_poll_wait_sec(),
            )
        if not isinstance(out, dict) or not out.get("ok"):
            reason = "p2p_loop_bad_result"
            if isinstance(out, dict):
                reason = str(out.get("reason") or reason)
            return [{"action": "strike", "reason": reason}]
        events = list(out.get("events") or [])
        if not events:
            if out.get("eof"):
                return [{"action": "eof"}]
            touches = int(out.get("keepalive_touches") or 0)
            if touches > 0:
                return [{"action": "keepalive", "touches": touches}]
            return [{"action": "idle"}]
        # Ingress rate admit on dispatch events only (fail → strike).
        normalized: list = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            action = str(ev.get("action") or "")
            if action == "dispatch":
                admitted = self._admit_pending_item(
                    {
                        "type": ev.get("type"),
                        "data": ev.get("data"),
                        "nbytes": int(ev.get("nbytes") or 0),
                    },
                    use_ingress=use_ingress,
                    rl_table=rl_table,
                    peer_key=peer_key,
                )
                if isinstance(admitted, WireReject):
                    normalized.append(
                        {"action": "strike", "reason": str(admitted.reason or "")}
                    )
                    # Stop delivering further dispatches after ingress reject.
                    break
                normalized.append(
                    {
                        "action": "dispatch",
                        "type": admitted.get("type"),
                        "data": admitted.get("data"),
                        "nbytes": int(ev.get("nbytes") or 0),
                    }
                )
            else:
                normalized.append(ev)
        if not normalized:
            return [{"action": "idle"}]
        self._pending_loop_events.extend(normalized[1:])
        return [normalized[0]]

    async def recv(self, config=None, *, rl_table=None, peer_key: str = "", use_ingress: bool = False):
        """Читает одно JSON-сообщение от пира.

        Returns:
            dict — valid envelope; WireReject — parse/size/rate fail; None — EOF;
            MSG_IDLE dict — read timeout (keep-alive).

        When use_ingress + rl_table: wire parse (+ optional rate) after native read.
        v1.3.92: P2PNativeConn.read_message fuses frame+parse in one to_thread hop.
        v1.3.94: prefers read_messages batch drain into `_pending_msgs`.
        """
        limit = _max_p2p_line_bytes(config)
        inbound = getattr(self, "_libp2p_inbound", None)
        if inbound is not None:
            try:
                item = await asyncio.wait_for(
                    inbound.get(), timeout=self._native_poll_wait_sec()
                )
            except asyncio.TimeoutError:
                return {"type": MSG_IDLE, "data": None}
            if item is None:
                return None
            if isinstance(item, dict) and item.get("wire_codec"):
                self._note_peer_wire_codec(item.get("wire_codec"))
            return item
        try:
            # v1.3.94/92: native transport fused read+wire parse (batch when available)
            if self._native_conn is not None and (
                hasattr(self._native_conn, "read_messages")
                or hasattr(self._native_conn, "read_message")
            ):
                if self._pending_msgs:
                    item = self._pending_msgs.pop(0)
                elif hasattr(self._native_conn, "read_messages"):
                    out = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._native_poll_read_call,
                            self._native_conn.read_messages,
                            int(self._native_read_batch or 8),
                            int(self._read_chunk or 65536),
                            list(ALLOWED_WIRE_TYPES),
                            bool(getattr(self, "_native_auto_pong", True)),
                        ),
                        timeout=self._native_poll_wait_sec(),
                    )
                    if not isinstance(out, dict) or not out.get("ok"):
                        reason = "bad_wire_line"
                        if isinstance(out, dict):
                            reason = str(out.get("reason") or reason)
                            # Partial messages before a hard reject — queue then reject next.
                            partial = list(out.get("messages") or [])
                            if partial and reason != "p2p_transport_timeout":
                                self._pending_msgs.extend(partial)
                                item = self._pending_msgs.pop(0)
                                return self._admit_pending_item(
                                    item, use_ingress=use_ingress, rl_table=rl_table, peer_key=peer_key
                                )
                        if reason == "p2p_transport_timeout":
                            raise asyncio.TimeoutError()
                        if reason == "p2p_line_too_large" or "p2p_line_too_large" in reason:
                            reason = "p2p_line_too_large"
                        logger.warning(
                            "[P2P] wire reject from %s (%s)",
                            self.peer_id or self.host,
                            reason,
                        )
                        return WireReject(reason)
                    msgs = list(out.get("messages") or [])
                    if not msgs:
                        if out.get("eof"):
                            return None
                        # v1.3.99: empty batch after keepalive skips → touch last_seen
                        if int(out.get("keepalive_touches") or 0) > 0 or int(
                            out.get("auto_pongs") or 0
                        ) > 0:
                            return {"type": MSG_PONG, "data": {"ts": time.time()}}
                        raise asyncio.TimeoutError()
                    self._pending_msgs.extend(msgs[1:])
                    item = msgs[0]
                    if out.get("eof") and not self._pending_msgs:
                        # eof with last message still to process — deliver it now
                        pass
                else:
                    out = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._native_poll_read_call,
                            self._native_conn.read_message,
                            int(self._read_chunk or 65536),
                            list(ALLOWED_WIRE_TYPES),
                            bool(getattr(self, "_native_auto_pong", True)),
                        ),
                        timeout=self._native_poll_wait_sec(),
                    )
                    if not isinstance(out, dict) or not out.get("ok"):
                        reason = "bad_wire_line"
                        if isinstance(out, dict):
                            reason = str(out.get("reason") or reason)
                        if reason == "p2p_transport_timeout":
                            raise asyncio.TimeoutError()
                        if reason == "p2p_line_too_large" or "p2p_line_too_large" in reason:
                            reason = "p2p_line_too_large"
                        logger.warning(
                            "[P2P] wire reject from %s (%s)",
                            self.peer_id or self.host,
                            reason,
                        )
                        return WireReject(reason)
                    if out.get("eof"):
                        return None
                    item = {
                        "type": out.get("type"),
                        "data": out.get("data"),
                        "nbytes": int(out.get("nbytes") or 0),
                        "wire_codec": out.get("wire_codec") or "v1",
                    }
                return self._admit_pending_item(
                    item, use_ingress=use_ingress, rl_table=rl_table, peer_key=peer_key
                )

            line = await self._read_wire_line(limit)
            if not line:
                return None
            if (
                use_ingress
                and rl_table is not None
                and (
                    getattr(self, "_transport_adapter", None) is not None
                    or hasattr(native, "p2p_ingress_admit")
                )
            ):
                peer_id = str(peer_key or self.peer_id or self.host or "")
                try:
                    def _do_admit():
                        adapter = getattr(self, "_transport_adapter", None)
                        if adapter is not None:
                            decision = adapter.admit_inbound_line(
                                line,
                                peer_id=peer_id,
                                now=float(time.time()),
                                max_bytes=int(limit),
                                allowed_types=list(ALLOWED_WIRE_TYPES),
                                rate_table=rl_table,
                            )
                            if not decision.accepted:
                                reason = (
                                    decision.reject.reason_code
                                    if decision.reject is not None
                                    else "bad_wire_line"
                                )
                                return {"ok": False, "reason": reason}
                            assert decision.frame is not None
                            self._note_peer_wire_codec(decision.frame.wire_codec)
                            return {
                                "ok": True,
                                "type": decision.frame.msg_type,
                                "data": decision.frame.data,
                                "wire_codec": decision.frame.wire_codec,
                            }
                        return native.p2p_ingress_admit(
                            line,
                            peer_id,
                            float(time.time()),
                            int(limit),
                            list(ALLOWED_WIRE_TYPES),
                            rl_table,
                        )

                    admitted = self._rl_call(_do_admit)
                except Exception as exc:
                    logger.warning(
                        "[P2P] ingress admit error from %s: %s",
                        self.peer_id or self.host,
                        exc,
                    )
                    return WireReject("ingress_error")
                if not isinstance(admitted, dict) or not admitted.get("ok"):
                    reason = "bad_wire_line"
                    if isinstance(admitted, dict):
                        reason = str(admitted.get("reason") or reason)
                    if reason == "p2p_line_too_large" or "p2p_line_too_large" in reason:
                        reason = "p2p_line_too_large"
                        logger.warning(
                            "[P2P] wire reject from %s (%s, %s bytes, limit=%s)",
                            self.peer_id or self.host,
                            reason,
                            len(line),
                            limit,
                        )
                    elif reason in (
                        "rate_limit_exceeded",
                        "exempt_rate_exceeded",
                        "bandwidth_exceeded",
                        "rate_limited",
                    ):
                        logger.warning(
                            "[P2P] ingress rate reject from %s (%s)",
                            self.peer_id or self.host,
                            reason,
                        )
                    else:
                        logger.warning(
                            "[P2P] wire reject from %s (%s, %s bytes)",
                            self.peer_id or self.host,
                            reason,
                            len(line),
                        )
                    return WireReject(reason)
                self._note_peer_wire_codec(admitted.get("wire_codec"))
                return {
                    "type": admitted.get("type"),
                    "data": admitted.get("data"),
                    "wire_codec": admitted.get("wire_codec")
                    or self._effective_wire_codec(),
                }
            try:
                parsed = native.parse_p2p_wire_line(
                    line,
                    max_bytes=limit,
                    allowed_types=list(ALLOWED_WIRE_TYPES),
                )
            except ValueError as exc:
                reason = str(exc) or "p2p_line_too_large"
                if "p2p_line_too_large" in reason:
                    reason = "p2p_line_too_large"
                logger.warning(
                    "[P2P] wire reject from %s (%s, %s bytes, limit=%s)",
                    self.peer_id or self.host,
                    reason,
                    len(line),
                    limit,
                )
                return WireReject(reason)
            if parsed is None:
                logger.warning(
                    "[P2P] bad wire line from %s (%s bytes)",
                    self.peer_id or self.host,
                    len(line),
                )
                return WireReject("bad_wire_line")
            if isinstance(parsed, dict):
                self._note_peer_wire_codec(parsed.get("wire_codec"))
            return parsed
        except asyncio.TimeoutError:
            return {"type": MSG_IDLE, "data": None}
        except ValueError as exc:
            reason = str(exc) or "bad_wire_line"
            if "p2p_line_too_large" in reason:
                reason = "p2p_line_too_large"
            elif "p2p_line_incomplete" in reason:
                reason = "p2p_line_incomplete"
            logger.warning(
                "[P2P] wire reject from %s (%s)",
                self.peer_id or self.host,
                reason,
            )
            return WireReject(reason)
        except Exception as exc:
            logger.warning(
                "[P2P] recv error from %s: %s",
                self.peer_id or self.host,
                exc,
            )
            return WireReject("recv_error")

    def close(self):
        worker = getattr(self, "_send_worker", None)
        if worker is not None and not worker.done():
            try:
                worker.cancel()
            except Exception as exc:
                logger.debug("[P2P] close cancel send worker failed: %s", exc)
        try:
            q = getattr(self, "_send_q", None)
            if q is not None:
                try:
                    q.put_nowait(None)
                except Exception as exc:
                    logger.debug("[P2P] close send_q wake failed: %s", exc)
            cq = getattr(self, "_send_ctrl_q", None)
            if cq is not None:
                try:
                    cq.put_nowait(None)
                except Exception as exc:
                    logger.debug("[P2P] close send_ctrl_q wake failed: %s", exc)
            rq = getattr(self, "_send_root_q", None)
            if rq is not None:
                try:
                    rq.put_nowait(None)
                except Exception as exc:
                    logger.debug("[P2P] close send_root_q wake failed: %s", exc)
            self._wake_send()
        except Exception as exc:
            logger.debug("[P2P] close send queues failed: %s", exc)
        q = getattr(self, "_libp2p_inbound", None)
        if q is not None:
            try:
                q.put_nowait(None)
            except Exception as exc:
                logger.debug("[P2P] libp2p inbound close wake failed: %s", exc)
        if self._native_conn is not None:
            try:
                self._native_io_call(self._native_conn.close)
            except Exception as exc:
                logger.debug(
                    "[P2P] native peer close failed %s:%s: %s", self.host, self.port, exc
                )
            return
        if self.writer is None:
            return
        try:
            self.writer.close()
        except Exception as exc:
            logger.debug("[P2P] peer close failed %s:%s: %s", self.host, self.port, exc)

    def __repr__(self) -> str:
        return f"Peer({self.peer_id[:8]}… {self.host}:{self.port} h={self.height})"


class P2PNode:
    """
    TCP P2P-узел: принимает входящие соединения и подключается к bootstrap пирам.
    Интегрирован с Blockchain, Mempool и EventBus.
    """

    def __init__(self, config, blockchain, mempool, bus=None):
        self.config = config
        self.blockchain = blockchain
        self.mempool = mempool
        self.bus = bus

        self.peer_manager: Optional[PeerManager] = None
        # ``peers`` is a property → PeerManager.peers (set after PeerManager boots).
        self._server: Optional[asyncio.Server] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Solicit waiters live exclusively on SyncSolicitHub (ADR 0003 C/D).
        # Alias `_sync_waiters` is assigned after hub construction below.
        self._peer_sync_locks: Dict[str, asyncio.Lock] = {}
        self._catch_up_apply_lock: Optional[asyncio.Lock] = None
        self._peer_msg_windows: Dict[str, tuple[int, float]] = {}
        self._peer_class_windows: Dict[str, tuple[int, float]] = {}
        self._peer_strikes: Dict[str, int] = {}
        self._peer_bans: Dict[str, float] = {}
        self._known_addrs: List[str] = []
        self._rl_table = None
        self._rl_lock = threading.RLock()
        self._conn_governor = None
        self._use_native_ingress = False
        self._use_native_egress = False
        self._peer_exempt_windows: Dict[str, tuple[int, float]] = {}
        self._egress_rejects: int = 0
        _want_native_rl = bool(
            getattr(config, "require_native_crypto", False)
            or getattr(config, "is_production", False)
        )
        if native.native_available() and hasattr(native, "P2PRateLimitTable"):
            try:
                self._rl_table = native.P2PRateLimitTable(
                    int(getattr(config, "p2p_max_messages_per_sec", 0) or 0),
                    int(getattr(config, "p2p_rate_limit_strikes", 5) or 5),
                    int(getattr(config, "p2p_ban_seconds", 300) or 300),
                    sorted(RATE_LIMIT_EXEMPT_TYPES),
                    int(getattr(config, "p2p_exempt_messages_per_sec", 0) or 0),
                    int(getattr(config, "p2p_max_bytes_per_sec", 0) or 0),
                    int(getattr(config, "p2p_max_outbound_bytes_per_sec", 0) or 0),
                )
                self._use_native_ingress = hasattr(native, "p2p_ingress_admit")
                self._use_native_egress = hasattr(self._rl_table, "admit_egress")
            except Exception as exc:
                if _want_native_rl:
                    raise RuntimeError(
                        f"P2PRateLimitTable required under require_native_crypto/prod: {exc}"
                    ) from exc
                logger.warning("[P2P] native P2PRateLimitTable unavailable: %s", exc)
                self._rl_table = None
                self._use_native_ingress = False
                self._use_native_egress = False
        self._conn_governor = None
        self._native_listener = None  # v1.3.90 P2PNativeListener
        self._use_native_transport = False
        self._native_tls = False
        self._native_accept_total = 0
        self._native_accept_errors = 0
        self._native_connect_total = 0
        if native.native_available() and hasattr(native, "P2PConnectionGovernor"):
            try:
                self._conn_governor = native.P2PConnectionGovernor(
                    int(getattr(config, "max_peers", 50) or 50),
                    int(getattr(config, "p2p_max_inbound_per_ip", 8) or 0),
                    int(getattr(config, "p2p_max_peers_per_subnet", 0) or 0),
                    int(getattr(config, "p2p_reserved_outbound_slots", 0) or 0),
                )
            except Exception as exc:
                logger.warning("[P2P] native P2PConnectionGovernor unavailable: %s", exc)
                self._conn_governor = None
        # Point 3: isolated peer mesh policy (lists / score / strike / ban / slots).
        self.peer_manager = PeerManager(
            PeerManagerSettings.from_config(config),
            rl_table=self._rl_table,
            rl_lock=self._rl_lock,
            conn_governor=self._conn_governor,
            native_helpers=native if native.native_available() else None,
        )
        self._known_addrs = self.peer_manager.known_addrs
        self._peer_strikes = self.peer_manager.strikes
        self._peer_bans = self.peer_manager.bans
        # v1.3.90/91: native TCP(+TLS) transport
        # v1.3.114: prod / require_native_crypto fail-closed (no silent asyncio fallback).
        want_native_tx = bool(getattr(config, "p2p_native_transport", False))
        must_native_tx = want_native_tx and (
            bool(getattr(config, "require_native_crypto", False))
            or str(getattr(config, "deployment_mode", "") or "").lower() == "prod"
        )
        if want_native_tx:
            if native.native_available() and hasattr(native, "P2PNativeListener"):
                if p2p_tls_enabled(config):
                    errs, _warn = validate_p2p_tls_config(config)
                    if errs:
                        msg = (
                            "[P2P] p2p_native_transport+TLS misconfigured: "
                            + "; ".join(errs)
                        )
                        if must_native_tx:
                            raise RuntimeError(msg)
                        logger.warning("%s", msg)
                    elif not getattr(native, "p2p_native_tls_available", lambda: False)():
                        msg = (
                            "[P2P] native TLS unavailable; "
                            "cannot use p2p_native_transport with TLS"
                        )
                        if must_native_tx:
                            raise RuntimeError(msg)
                        logger.warning("%s", msg)
                    else:
                        self._use_native_transport = True
                else:
                    self._use_native_transport = True
            else:
                msg = "[P2P] p2p_native_transport requested but abs_native missing"
                if must_native_tx:
                    raise RuntimeError(msg)
                logger.warning("%s", msg)
        self._native_tls = bool(
            self._use_native_transport and p2p_tls_enabled(config)
        )
        # ADR 0020: libp2p live mesh — never run native TCP listener in parallel.
        self._use_libp2p_transport = bool(getattr(config, "feature_libp2p", False))
        self._libp2p_sessions: Dict[str, PeerConnection] = {}
        self._libp2p_listening = False
        self._libp2p_listen_addrs: List[str] = []
        self._libp2p_wire_refuse_total = 0
        if self._use_libp2p_transport:
            self._use_native_transport = False
            self._native_tls = False
        self._native_read_message = False
        self._native_write_message = False
        self._native_read_messages = False
        self._native_write_messages = False
        self._native_handshake = False
        self._native_peer_identities = False
        self._native_auto_pong = False
        self._native_read_batch = _clamp_native_batch(
            getattr(config, "p2p_native_read_batch", 8), 8
        )
        self._native_write_batch = _clamp_native_batch(
            getattr(config, "p2p_native_write_batch", 8), 8
        )
        self._native_read_chunk = _clamp_native_chunk(
            getattr(config, "p2p_native_read_chunk", 65536), 65536
        )
        self._native_io_timeout_ms = _clamp_native_timeout_ms(
            getattr(config, "p2p_native_io_timeout_ms", 30000), 30000
        )
        self._native_poll_timeout_ms = max(
            20,
            min(2000, int(getattr(config, "p2p_native_poll_timeout_ms", 100) or 100)),
        )
        if self._use_native_transport:
            try:
                import abs_native as _abs_nat

                _cls = getattr(_abs_nat, "P2PNativeConn", None)
                self._native_read_message = hasattr(_cls, "read_message")
                self._native_write_message = hasattr(_cls, "write_message")
                self._native_read_messages = hasattr(_cls, "read_messages")
                self._native_write_messages = hasattr(_cls, "write_messages") and hasattr(
                    _cls, "write_payloads"
                )
                self._native_handshake = hasattr(_cls, "handshake_roundtrip")
                self._native_peer_identities = hasattr(_cls, "peer_cert_identities")
                self._native_message_loop_shell = hasattr(
                    _cls, "read_message_loop_events"
                )
                self._native_auto_pong = bool(
                    getattr(config, "p2p_native_auto_pong", True)
                )
                if must_native_tx and not self._native_message_loop_shell:
                    raise RuntimeError(
                        "[P2P] p2p_native_transport requires "
                        "P2PNativeConn.read_message_loop_events "
                        "(rebuild/install abs_native; stale wheel is not prod-safe)"
                    )
            except RuntimeError:
                raise
            except Exception as exc:
                logger.warning("[P2P] native capability probe failed: %s", exc)
                self._native_read_message = False
                self._native_write_message = False
                self._native_read_messages = False
                self._native_write_messages = False
                self._native_handshake = False
                self._native_peer_identities = False
                self._native_message_loop_shell = False
                self._native_auto_pong = False
                if must_native_tx:
                    raise RuntimeError(
                        "[P2P] native capability probe failed under "
                        "prod/require_native_crypto"
                    ) from exc
        else:
            self._native_message_loop_shell = False
        self._native_message_loop_dispatch_total: int = 0
        self._native_message_loop_strikes_total: int = 0
        self._attestation_semantic_rejects_total: int = 0
        self._tx_semantic_rejects_total: int = 0
        self._block_semantic_rejects_total: int = 0
        self._state_root_semantic_rejects_total: int = 0
        self._status_semantic_rejects_total: int = 0
        self._blocks_response_semantic_rejects_total: int = 0
        self._block_response_semantic_rejects_total: int = 0
        self._state_root_response_request_rejects_total: int = 0
        self._state_root_outbound_refuse_total: int = 0
        self._discovery_dial_rejects_total: int = 0
        self._handshake_head_rejects_total: int = 0
        self._status_height_head_rejects_total: int = 0
        self._unsolicited_mempool_rejects_total: int = 0
        self._status_height_cap_total: int = 0
        self._new_block_height_cap_total: int = 0
        self._new_block_head_height_mismatch_total: int = 0
        self._new_block_announce_body_refuse_total: int = 0
        self._new_block_contiguous_parent_mismatch_total: int = 0
        self._new_block_same_height_parent_mismatch_total: int = 0
        self._new_block_tip_head_mismatch_total: int = 0
        self._status_head_height_mismatch_total: int = 0
        self._status_head_without_height_total: int = 0
        self._handshake_head_without_height_total: int = 0
        self._handshake_height_cap_total: int = 0
        self._state_root_local_rejects_total: int = 0
        self._attestation_slot_ahead_rejects_total: int = 0
        self._attestation_local_head_rejects_total: int = 0
        self._attestation_echo_drops_total: int = 0
        self._attestation_dup_drops_total: int = 0
        self._attestation_seen: Dict[tuple, float] = {}
        self._attestation_target_head_rejects_total: int = 0
        self._unsolicited_block_rejects_total: int = 0
        self._unsolicited_state_root_rejects_total: int = 0
        self._state_root_late: Dict[str, tuple] = {}
        self._state_root_timeout_at: Dict[str, float] = {}
        self._state_root_late_accepts_total: int = 0
        self._unsolicited_peers_rejects_total: int = 0
        self._catch_up_no_head_refuse_total: int = 0
        self._catch_up_head_height_mismatch_total: int = 0
        self._catch_up_tip_probe_refuse_total: int = 0
        self._catch_up_peer_head_probe_refuse_total: int = 0
        self._catch_up_tip_head_mismatch_total: int = 0
        self._catch_up_contiguous_parent_mismatch_total: int = 0
        self._catch_up_height_continuity_mismatch_total: int = 0
        self._fork_peer_head_probe_refuse_total: int = 0
        self._reconcile_head_hash_mismatch_total: int = 0
        self._ghost_head_probe_refuse_total: int = 0
        self._reconcile_contiguous_parent_mismatch_total: int = 0
        self._reconcile_same_height_parent_mismatch_total: int = 0
        self._reconcile_tip_head_mismatch_total: int = 0
        self._bootstrap_redial_total: int = 0
        self._bootstrap_pin_rejects_total: int = 0
        # boot_addr ("node2:5000") → peer_id once covered (outbound dial or inbound bind)
        self._bootstrap_peer_ids: dict = {}
        self._handshake_rejects: int = 0
        self._eclipse_at_risk: int = 0
        self._eclipse_ratio: float = 0.0
        self._eclipse_unique_public_subnets: int = 0
        self._eclipse_public_peers: int = 0
        self._eclipse_prune_total: int = 0
        self._attestation_local_fail: int = 0
        self._propagation_log_fail: int = 0
        self._peer_connect_task_fail: int = 0
        self._peer_status_send_fail: int = 0
        self._peer_send_fail: int = 0
        self._broadcast_fail: int = 0
        self._maintenance_loop_fail: int = 0
        self._catch_up_loop_fail: int = 0
        self._peer_tx_reject: int = 0
        self._mempool_dup_refuse_total: int = 0
        self._mempool_fee_refuse_total: int = 0
        self._mempool_fee_high_refuse_total: int = 0
        self._mempool_gas_refuse_total: int = 0
        self._mempool_calldata_refuse_total: int = 0
        self._mempool_value_refuse_total: int = 0
        self._mempool_value_high_refuse_total: int = 0
        self._mempool_nonce_refuse_total: int = 0
        self._mempool_nonce_high_refuse_total: int = 0
        self._mempool_fee_negative_refuse_total: int = 0
        self._mempool_gas_negative_refuse_total: int = 0
        self._mempool_gas_unparseable_refuse_total: int = 0
        self._mempool_value_unparseable_refuse_total: int = 0
        self._mempool_fee_unparseable_refuse_total: int = 0
        self._mempool_nonce_unparseable_refuse_total: int = 0
        self._mempool_empty_from_refuse_total: int = 0
        self._mempool_from_size_refuse_total: int = 0
        self._mempool_empty_to_refuse_total: int = 0
        self._mempool_to_size_refuse_total: int = 0
        self._mempool_empty_hash_refuse_total: int = 0
        self._mempool_hash_size_refuse_total: int = 0
        self._mempool_empty_sig_refuse_total: int = 0
        self._mempool_empty_pubkey_refuse_total: int = 0
        self._mempool_sig_size_refuse_total: int = 0
        self._mempool_pubkey_size_refuse_total: int = 0
        self._mempool_nonfinite_value_refuse_total: int = 0
        self._mempool_nonfinite_fee_refuse_total: int = 0
        self._get_blocks_future_refuse_total: int = 0
        self._get_block_future_refuse_total: int = 0
        self._get_blocks_past_tip_clamp_total: int = 0
        self._get_mempool_tip_misaligned_total: int = 0
        self._import_block_fail: int = 0
        self._import_offload_total: int = 0
        self.apply_queue = None  # set by AbsoluteNode — serial mine+import
        self.sync_executor = None  # dedicated pool for sync_state (not default executor)
        # Stage 2 tip-safety shadow observer (set by AbsoluteNode; observe-only).
        self.tip_safety_shadow = None
        # Step C: transport boundary facade (always present; gates use existing flags).
        from network.transport import NativeTransportAdapter

        self.transport_adapter = NativeTransportAdapter(
            require_native=bool(_want_native_rl),
        )
        # ADR 0019: dual-stack selector + PeerManager ban hooks (FEATURE_LIBP2P lab).
        from network.transport.dual_stack import DualStackDialer
        from network.transport.libp2p_adapter.peer_policy import Libp2pPeerPolicy

        self._dual_stack = DualStackDialer.from_config(self.config)
        self._dual_stack.attach_peer_policy(
            Libp2pPeerPolicy(peer_manager=self.peer_manager)
        )
        # Step D: application dispatcher (type → handler registry; tip-evidence DI).
        from network.p2p_dispatch import (
            TipSafetyEvidenceBridge,
            build_default_dispatcher,
        )

        self._dispatch_tip_evidence_refuse_total: int = 0
        self._tip_evidence_bridge = TipSafetyEvidenceBridge(
            shadow_provider=lambda: getattr(self, "tip_safety_shadow", None),
        )
        self.dispatcher = build_default_dispatcher(
            tip_evidence=self._tip_evidence_bridge,
        )
        self._sync_fail: int = 0
        self._peer_sync_fail: int = 0
        self._discovery_loop_fail: int = 0
        self._bootstrap_loop_fail: int = 0
        self._last_tx_wire_reject: str = ""
        self._shape_reject_counts: Dict[str, int] = self.peer_manager.shape_reject_counts
        self._consensus = None
        # v1.3.66: coalesce duplicate sync/connect tasks
        self._sync_tasks: Dict[str, asyncio.Task] = {}
        self._connect_tasks: Dict[str, asyncio.Task] = {}
        # Coalesce concurrent state_root solicits (HTTP harness + sync_state).
        self._state_root_probe_task: Optional[asyncio.Task] = None
        self._state_root_probe_lock: Optional[asyncio.Lock] = None
        self._wire_probe_hold_until: float = 0.0
        self._outbound_drops: int = 0
        self._sync_admission_rejects: int = 0
        self.validator_keys = None
        # Fail-closed until SyncEngine.sync_state proves peer roots match.
        self._state_consistent = False
        self._sharding = None
        # ADR 0003 Step C/D: solicit waiter hub owns arm/fulfill/timeout.
        # `_handle_message` only forwards — never inspects waiter tables.
        from sync.solicit import SyncSolicitHub

        self.solicit_hub = SyncSolicitHub(
            peers_solicit_only=bool(
                getattr(config, "p2p_peers_solicit_only", True)
            ),
            verify_blocks=getattr(native, "verify_p2p_blocks_response_semantics", None),
            verify_block=getattr(native, "verify_p2p_block_response_semantics", None),
            verify_state_root=getattr(
                native, "verify_p2p_state_root_response_request_semantics", None
            ),
            default_max_age_sec=float(
                getattr(config, "p2p_solicit_waiter_max_age_sec", 120.0) or 120.0
            ),
        )
        # Back-compat read-only-ish alias (same mapping object as hub.waiters).
        self._sync_waiters = self.solicit_hub.waiters
        # Per-kind solicit locks: state_root must not wait behind mempool/blocks.
        self._solicit_peer_locks: Dict[str, asyncio.Lock] = {}
        # Catch-up pure policy + orchestrator gates (ADR 0003).
        from sync.catchup import CatchUpOrchestrator, CatchUpPolicy

        self.catch_up_policy = CatchUpPolicy()
        self.catch_up = CatchUpOrchestrator(self.catch_up_policy)

        # Подписка на события шины — транслируем в сеть
        if self.bus:
            self.bus.on("block.new", self._on_local_block)
            self.bus.on("tx.new", self._on_local_tx)
            self.bus.on("consensus.attestation", self._on_consensus_attestation)

        # SyncEngine (System C) — fast catch-up
        if _SYNC_ENGINE_AVAILABLE:
            self.sync_engine = SyncEngine(node=self)
            print("[P2P] SyncEngine: enabled (fast catch-up)")
        else:
            self.sync_engine = None

    def force_inconsistent(self, reason: str = "forced") -> None:
        """Fail-closed lockdown via ConsistencyService (single writer)."""
        eng = getattr(self, "sync_engine", None)
        svc = getattr(eng, "consistency", None) if eng is not None else None
        if svc is not None:
            svc.request_lockdown(str(reason or "forced"))
            return
        self._state_consistent = False

    async def refresh_consistency(self) -> bool:
        """Re-evaluate consistency through SyncEngine / ConsistencyService."""
        if not self.sync_engine:
            self.force_inconsistent("no_sync_engine")
            return False
        return bool(await self._sync_state_async())

    def head(self) -> Optional[str]:
        """Current head block hash for SyncEngine."""
        last = self.blockchain.get_last_block()
        if not isinstance(last, dict):
            return None
        h = last.get("hash")
        return str(h) if h else None

    def _try_local_head(self) -> tuple[Optional[str], str]:
        """Local tip hash. ``(None, local_tip_unreadable)`` if lookup failed.

        Empty string means lookup succeeded but tip is unresolved (soft-skip).
        Bind paths must refuse ``local_tip_unreadable`` — not skip the check.
        """
        try:
            raw = self.head()
        except Exception as exc:
            logger.warning("[P2P] head() failed: %s", exc)
            return None, "local_tip_unreadable"
        if raw is None:
            return "", ""
        return str(raw).strip(), ""

    def _try_expected_parent(self, height: int) -> tuple[Optional[str], str]:
        """Tip-height parent hash. ``(None, local_parent_unreadable)`` on lookup fail."""
        try:
            return str(self._expected_parent_for_height(int(height)) or "").strip(), ""
        except Exception as exc:
            logger.warning("[P2P] expected parent lookup failed: %s", exc)
            return None, "local_parent_unreadable"

    @property
    def height(self) -> int:
        return self.blockchain.get_height()

    @property
    def consensus(self):
        return self._consensus

    @consensus.setter
    def consensus(self, value):
        self._consensus = value

    def set_consensus(self, consensus, validator_keys=None) -> None:
        """Wire consensus for attestation gossip and fork choice."""
        self._consensus = consensus
        self.validator_keys = validator_keys

    def _consensus_adapter(self):
        return self._consensus or getattr(self.blockchain, "consensus_adapter", None)

    def _feed_fork_choice(self, block_data: Dict) -> None:
        """Register block in LMD-GHOST tree (competing forks at same height)."""
        if not isinstance(block_data, dict):
            return
        ca = self._consensus_adapter()
        if not ca or not hasattr(ca, "add_block_to_fork_choice"):
            return
        ca.add_block_to_fork_choice({
            "hash": block_data.get("hash", ""),
            "parent_hash": block_data.get("parent_hash", ""),
            "number": int(block_data.get("height", block_data.get("number", 0)) or 0),
        })

    def _ghost_canonical_head(self) -> Optional[str]:
        ca = self._consensus_adapter()
        if ca and hasattr(ca, "get_canonical_head"):
            return ca.get_canonical_head()
        return None

    def _peer_with_head(self, head_hash: str) -> Optional[PeerConnection]:
        target = (head_hash or "").strip().lower()
        if not target:
            return None
        for peer in self.peers.values():
            peer_head = (peer.head or "").strip().lower()
            if peer_head == target or target in peer_head or peer_head in target:
                return peer
        return None

    def set_sharding(self, sharding) -> None:
        """Wire distributed sharding for cross-shard gossip."""
        self._sharding = sharding
        if sharding is not None and hasattr(sharding, "set_gossip_callback"):
            sharding.set_gossip_callback(self._schedule_cross_shard_gossip)

    def _schedule_cross_shard_gossip(self, payload: Dict) -> None:
        if self._loop and self._running:
            if isinstance(payload, dict) and payload.get("type") == "shard_migration":
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_shard_migration(payload), self._loop
                )
            elif isinstance(payload, dict) and payload.get("type") == "cross_shard_ack":
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_cross_shard_ack(payload), self._loop
                )
            else:
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_cross_shard_tx(payload), self._loop
                )

    def get_block(self, block_hash: str) -> Optional[Dict]:
        """For SyncEngine.download_chain()."""
        if hasattr(self.blockchain, "get_block_by_hash"):
            return self.blockchain.get_block_by_hash(block_hash)
        return None

    # ── DispatchHost surface (Step D — structural Protocol for P2PDispatcher) ─

    @property
    def peers(self) -> Dict[str, PeerConnection]:
        """Live mesh map — always the PeerManager registry (never a detached dict)."""
        return self.peer_manager.peers

    @peers.setter
    def peers(self, value: Dict[str, PeerConnection]) -> None:
        """Replace mesh contents in-place (tests may assign a new mapping)."""
        live = self.peer_manager.peers
        live.clear()
        if value:
            live.update(value)

    def strike_peer(self, peer: PeerConnection, reason: str) -> bool:
        """DispatchHost: strike peer; True if peer should be removed."""
        return bool(self._strike_peer_sync(peer, reason))

    def remove_peer(self, peer_id: str, peer: Any = None) -> None:
        """DispatchHost: remove peer from the mesh."""
        self._remove_peer(peer_id, peer)

    def bump_counter(self, name: str, delta: int = 1) -> None:
        """DispatchHost: increment a node counter by public name."""
        attr = name if str(name).startswith("_") else f"_{name}"
        cur = int(getattr(self, attr, 0) or 0)
        setattr(self, attr, cur + int(delta))

    async def handle_new_block(self, peer: PeerConnection, data: Any) -> None:
        await self._handle_new_block(peer, data)

    async def handle_get_blocks(self, peer: PeerConnection, data: Any) -> None:
        await self._handle_get_blocks(peer, data)

    async def handle_new_tx(self, peer: PeerConnection, data: Any) -> None:
        await self._handle_new_tx(peer, data)

    async def handle_get_mempool(self, peer: PeerConnection) -> None:
        await self._handle_get_mempool(peer)

    async def handle_attestation(self, peer: PeerConnection, data: Any) -> None:
        await self._handle_attestation(peer, data)

    async def handle_validator_register(self, peer: PeerConnection, data: Any) -> None:
        await self._handle_validator_register(peer, data)

    async def handle_cross_shard_tx(self, peer: PeerConnection, data: Any) -> None:
        await self._handle_cross_shard_tx(peer, data)

    async def handle_cross_shard_ack(self, peer: PeerConnection, data: Any) -> None:
        await self._handle_cross_shard_ack(peer, data)

    async def handle_shard_migration(self, peer: PeerConnection, data: Any) -> None:
        await self._handle_shard_migration(peer, data)

    def get_block_future_refuse_reason(self, height: int) -> str:
        return self._get_block_future_refuse_reason(height)

    def cap_claimed_peer_height(self, height: int) -> tuple:
        return self._cap_claimed_peer_height(height)

    def status_head_height_refuse_reason(self, head_hash: str, height: int) -> str:
        return self._status_head_height_refuse_reason(head_hash, height)

    def ingest_discovered_peers(self, peer: PeerConnection, data: Any) -> None:
        self._ingest_discovered_peers(peer, data)

    def state_root_response_for_height(self, height: int) -> Any:
        return self._state_root_response_for_height(height)

    def _tip_safety_precheck(self, block_data: Dict) -> bool:
        """Run tip-safety observe/enforce before chain import.

        Returns:
            True if import may proceed; False if enforce refused the candidate.
        """
        shadow = getattr(self, "tip_safety_shadow", None)
        if shadow is None:
            return True
        q = getattr(self, "apply_queue", None)
        try:
            cand_h = int((block_data or {}).get("height") or 0)
        except (TypeError, ValueError):
            cand_h = 0
        try:
            tip_h = int(self.blockchain.get_height() or 0) if self.blockchain else 0
        except (TypeError, ValueError, AttributeError):
            tip_h = 0
        last_forge = int(getattr(self, "_last_local_forge_height", 0) or 0)
        # Only the just-forged height and the next pipeline height. Never
        # ``cand <= last_forge`` — that would skip tip-safety for the whole
        # history on the miner.
        if last_forge > 0 and cand_h in (last_forge, last_forge + 1):
            logger.info(
                "[P2P] tip_safety defer own-forge echo height=%s last_forge=%s",
                cand_h,
                last_forge,
            )
            return True
        if should_defer_tip_safety_skip_ahead(
            apply_busy=bool(q is not None and getattr(q, "busy", False)),
            candidate_height=cand_h,
            tip_height=tip_h,
        ):
            logger.info(
                "[P2P] tip_safety defer skip-ahead height=%s tip=%s (apply_queue busy)",
                cand_h,
                tip_h,
            )
            return True
        decision = None
        try:
            decision = shadow.observe_before_import(block_data, self.blockchain)
        except Exception as exc:
            logger.warning("[P2P] tip_safety observe suppressed: %s", exc)
            decision = None
        if bool(getattr(shadow, "enforce", False)) and not shadow.allows_import(
            decision
        ):
            code = shadow.record_enforce_refuse(decision)
            self._import_block_fail = int(self._import_block_fail or 0) + 1
            logger.warning("[P2P] tip_safety enforce refused import (%s)", code)
            return False
        return True

    def import_block(self, block_data: Dict) -> bool:
        """For SyncEngine.fast_sync() (must stay sync — often already on a worker thread)."""
        if not self._tip_safety_precheck(block_data):
            return False
        shadow = getattr(self, "tip_safety_shadow", None)
        q = getattr(self, "apply_queue", None)
        if q is not None:
            self._import_offload_total = int(self._import_offload_total or 0) + 1
            ok = bool(q.submit_import(block_data))
            if not ok:
                self._import_block_fail = int(self._import_block_fail or 0) + 1
                logger.warning("[P2P] import_block rejected (apply queue)")
            if shadow is not None:
                try:
                    shadow.note_import_result(ok, self.blockchain)
                except Exception as exc:
                    logger.warning("[P2P] tip_safety note suppressed: %s", exc)
            return ok
        try:
            if hasattr(self.blockchain, "import_block"):
                ok = bool(self.blockchain.import_block(block_data))
            else:
                from core.blockchain import Block

                blk = Block.from_dict(block_data)
                ok = bool(self.blockchain.add_block(blk))
            if not ok:
                self._import_block_fail = int(self._import_block_fail or 0) + 1
                logger.warning("[P2P] import_block rejected")
            if shadow is not None:
                try:
                    shadow.note_import_result(ok, self.blockchain)
                except Exception as exc:
                    logger.warning("[P2P] tip_safety note suppressed: %s", exc)
            return ok
        except Exception as exc:
            self._import_block_fail = int(self._import_block_fail or 0) + 1
            logger.warning("[P2P] import_block failed: %s", exc)
            if shadow is not None:
                try:
                    shadow.note_import_result(False, self.blockchain)
                except Exception as note_exc:
                    logger.warning(
                        "[P2P] tip_safety note suppressed: %s", note_exc
                    )
            return False

    async def _import_block_async(self, block_data: Dict) -> bool:
        """Offload chain apply so the asyncio loop stays responsive under EVM load."""
        self._import_offload_total = int(self._import_offload_total or 0) + 1
        if not self._tip_safety_precheck(block_data):
            return False
        shadow = getattr(self, "tip_safety_shadow", None)
        q = getattr(self, "apply_queue", None)
        if q is not None:
            ok = bool(await q.submit_import_async(block_data))
        else:
            ok = bool(
                await asyncio.to_thread(self._import_block_without_shadow, block_data)
            )
        if shadow is not None:
            try:
                shadow.note_import_result(ok, self.blockchain)
            except Exception as exc:
                logger.warning("[P2P] tip_safety note suppressed: %s", exc)
        return ok

    def _import_block_without_shadow(self, block_data: Dict) -> bool:
        """Direct chain import used by async offload when no apply queue is set.

        Intentionally skips shadow hooks — caller (``_import_block_async``)
        already observed/noted around this call to avoid double-counting.
        """
        try:
            if hasattr(self.blockchain, "import_block"):
                ok = bool(self.blockchain.import_block(block_data))
            else:
                from core.blockchain import Block

                blk = Block.from_dict(block_data)
                ok = bool(self.blockchain.add_block(blk))
            if not ok:
                self._import_block_fail = int(self._import_block_fail or 0) + 1
                logger.warning("[P2P] import_block rejected")
            return ok
        except Exception as exc:
            self._import_block_fail = int(self._import_block_fail or 0) + 1
            logger.warning("[P2P] import_block failed: %s", exc)
            return False

    async def _sync_state_async(self) -> bool:
        """Run SyncEngine.sync_state on the dedicated sync executor (not default pool)."""
        if not self.sync_engine:
            return False
        loop = asyncio.get_running_loop()
        ex = getattr(self, "sync_executor", None)
        return bool(await loop.run_in_executor(ex, self.sync_engine.sync_state))

    def _reorg_and_import(self, rollback_to: int, peer_block: Dict) -> bool:
        """Sync reorg+import for worker-thread execution."""
        q = getattr(self, "apply_queue", None)
        if q is not None:
            return bool(q.submit_reorg_and_import(int(rollback_to), peer_block))
        if not self.blockchain.reorg_to_ancestor(int(rollback_to)):
            return False
        return bool(self.import_block(peer_block))

    async def _reorg_and_import_async(self, rollback_to: int, peer_block: Dict) -> bool:
        """Offload reorg+import from async reconcile paths."""
        self._import_offload_total = int(self._import_offload_total or 0) + 1
        q = getattr(self, "apply_queue", None)
        if q is not None:
            return bool(await q.submit_reorg_and_import_async(int(rollback_to), peer_block))
        return await asyncio.to_thread(self._reorg_and_import, int(rollback_to), peer_block)

    # ── Запуск / остановка ───────────────────────────────────────────────────

    async def start(self):
        """Запускает TCP-сервер и подключается к bootstrap пирам."""
        self._running = True
        self._loop = asyncio.get_event_loop()

        # Запускаем TCP-сервер (asyncio TLS path OR native plain-TCP transport)
        try:
            if self._use_libp2p_transport:
                await self._start_libp2p_listen()
            elif self._use_native_transport:
                if self._native_tls:
                    tls_errors, tls_warn = validate_p2p_tls_config(self.config)
                    for warn in tls_warn:
                        logger.warning("[P2P] TLS: %s", warn)
                    if tls_errors:
                        print(f"[P2P] native TLS misconfigured: {tls_errors}")
                        self._running = False
                        return
                max_bytes = _max_p2p_line_bytes(self.config)
                tls_kwargs = {}
                if self._native_tls:
                    tls_kwargs = {
                        "cert_path": str(
                            getattr(self.config, "p2p_tls_cert_path", "") or ""
                        ),
                        "key_path": str(
                            getattr(self.config, "p2p_tls_key_path", "") or ""
                        ),
                        "ca_path": str(getattr(self.config, "p2p_tls_ca_path", "") or ""),
                        "require_client_cert": bool(
                            getattr(self.config, "p2p_tls_require_client_cert", True)
                        ),
                    }
                self._native_listener = native.P2PNativeListener(
                    str(self.config.p2p_host or "0.0.0.0"),
                    int(self.config.p2p_port),
                    int(max_bytes),
                    500,
                    **tls_kwargs,
                )
                label = "native-tls" if self._native_tls else "native-tcp"
                print(
                    f"[P2P] Listening on {self.config.p2p_host}:{self.config.p2p_port} "
                    f"({label} v1.3.140)"
                )
            else:
                if p2p_tls_enabled(self.config):
                    tls_errors, tls_warn = validate_p2p_tls_config(self.config)
                    for warn in tls_warn:
                        logger.warning("[P2P] TLS: %s", warn)
                    if tls_errors:
                        print(f"[P2P] TLS enabled but misconfigured: {tls_errors}")
                        self._running = False
                        return
                server_ssl = build_p2p_server_ssl_context(self.config)
                self._server = await asyncio.start_server(
                    self._handle_incoming,
                    self.config.p2p_host,
                    self.config.p2p_port,
                    ssl=server_ssl,
                )
                tls_label = "tls" if server_ssl else "plain"
                print(
                    f"[P2P] Listening on {self.config.p2p_host}:{self.config.p2p_port} ({tls_label})"
                )
        except RuntimeError as e:
            print(f"[P2P] libp2p start refused: {e}")
            self._running = False
            return
        except OSError as e:
            print(f"[P2P] Could not bind port {self.config.p2p_port}: {e}")
            print("[P2P] Hint: stop other node — .\\scripts\\stop_node.ps1 — or use --port 5001")
            # Bind failure must not leave the node advertised as running.
            self._running = False
            return

        # Подключаемся к bootstrap пирам
        for peer_addr in self.config.bootstrap_peers:
            parts = peer_addr.split(":")
            if len(parts) == 2:
                self._schedule_connect(parts[0], int(parts[1]))

        # Периодические задачи
        asyncio.create_task(self._ping_loop())
        asyncio.create_task(self._discovery_loop())
        asyncio.create_task(self._bootstrap_retry_loop())
        asyncio.create_task(self._maintenance_loop())
        asyncio.create_task(self._solo_node_hint())
        asyncio.create_task(self._catch_up_loop())

        if self._use_libp2p_transport:
            await self._libp2p_inbox_loop()
        elif self._use_native_transport and self._native_listener is not None:
            await self._native_accept_loop()
        elif self._server:
            async with self._server:
                await self._server.serve_forever()

    async def _start_libp2p_listen(self) -> None:
        """Listen on rust-libp2p swarm. Fail closed if native swarm is missing."""
        from network.transport.libp2p_adapter.adapter import native_libp2p_available

        adapter = self._dual_stack.libp2p
        if not native_libp2p_available() or not adapter.rust_backend:
            raise RuntimeError(
                "feature_libp2p=true but abs_native.libp2p_available() is false "
                "(rebuild with Cargo feature libp2p; no TCP+TLS fallback)"
            )
        port = int(self.config.p2p_port)
        host = str(self.config.p2p_host or "0.0.0.0")
        if host in ("0.0.0.0", "::", ""):
            ma = f"/ip4/0.0.0.0/tcp/{port}"
        else:
            ma = f"/ip4/{host}/tcp/{port}"
        addrs = await asyncio.to_thread(adapter.listen, ma)
        self._libp2p_listen_addrs = [str(a) for a in (addrs or [])]
        self._libp2p_listening = True
        print(
            f"[P2P] Listening on {ma} (libp2p Noise/Yamux ADR 0020) "
            f"addrs={self._libp2p_listen_addrs}"
        )

    def _libp2p_admit_raw_frame(self, peer_id: str, frame: bytes) -> Optional[Dict]:
        """Admit one `/abs/wire` frame. None means REFUSE (do not dispatch)."""
        from network.transport.libp2p_adapter.wire_bridge import admit_abs_wire_frame

        decision = admit_abs_wire_frame(
            bytes(frame),
            peer_id=str(peer_id),
            rate_table=self._rl_table,
            max_bytes=_max_p2p_line_bytes(self.config),
            allowed_types=list(ALLOWED_WIRE_TYPES),
        )
        if (not decision.ok) or decision.frame is None:
            self._libp2p_wire_refuse_total = int(self._libp2p_wire_refuse_total or 0) + 1
            return None
        fr = decision.frame
        return {
            "type": fr.msg_type,
            "data": fr.data,
            "wire_codec": fr.wire_codec,
            "nbytes": int(fr.raw_len),
        }

    def _new_libp2p_peer(self, host: str, port: int, libp2p_peer_id: str) -> PeerConnection:
        existing = self._libp2p_sessions.get(str(libp2p_peer_id))
        if existing is not None:
            if host and str(existing.host or "") in ("", "?", "libp2p"):
                existing.host = str(host)
            if int(port or 0) > 0:
                existing.port = int(port)
            return existing
        qmax, dto = self._peer_send_queue_params()
        peer = PeerConnection(
            None,
            None,
            send_queue_max=qmax,
            drain_timeout_sec=dto,
            libp2p_adapter=self._dual_stack.libp2p,
            libp2p_peer_id=str(libp2p_peer_id),
        )
        peer.host = str(host or libp2p_peer_id[:16] or "libp2p")
        peer.port = int(port or 0)
        self._libp2p_sessions[str(libp2p_peer_id)] = peer
        return peer

    async def _libp2p_on_raw_frame(self, peer_id: str, frame: bytes) -> None:
        admitted = self._libp2p_admit_raw_frame(peer_id, frame)
        if admitted is None:
            return
        pid = str(peer_id)
        peer = self._libp2p_sessions.get(pid)
        spawn_inbound = False
        if peer is None:
            peer = self._new_libp2p_peer("", 0, pid)
            self._attach_peer_hooks(peer)
            spawn_inbound = True
        elif str(getattr(peer, "_libp2p_role", "") or "") != "outbound" and not getattr(
            peer, "_libp2p_inbound_handler", False
        ):
            spawn_inbound = True
        q = getattr(peer, "_libp2p_inbound", None)
        if q is None:
            return
        try:
            q.put_nowait(admitted)
        except asyncio.QueueFull:
            self._libp2p_wire_refuse_total = int(self._libp2p_wire_refuse_total or 0) + 1
            return
        if spawn_inbound and not getattr(peer, "_libp2p_inbound_handler", False):
            peer._libp2p_inbound_handler = True
            asyncio.create_task(self._handle_libp2p_incoming(peer))

    async def _libp2p_inbox_loop(self) -> None:
        adapter = self._dual_stack.libp2p
        while self._running:
            try:
                items = await asyncio.to_thread(adapter.poll_inbox)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    break
                logger.warning("[P2P] libp2p poll_inbox error: %s", exc)
                await asyncio.sleep(0.2)
                continue
            if not items:
                await asyncio.sleep(0.05)
                continue
            for peer_id, frame in items:
                try:
                    await self._libp2p_on_raw_frame(str(peer_id), bytes(frame))
                except Exception as exc:
                    logger.warning("[P2P] libp2p inbound frame error: %s", exc)

    async def _handle_libp2p_incoming(self, peer: PeerConnection) -> None:
        """Inbound Absolute session over rust-libp2p `/abs/wire`."""
        if self._is_addr_banned(peer.host, peer.port):
            peer.close()
            return
        admit = self.peer_manager.allow_inbound(str(peer.host or ""))
        if not admit.allowed:
            self._handshake_rejects = int(self._handshake_rejects or 0) + 1
            await peer.send(
                MSG_HANDSHAKE_ACK,
                {"accepted": False, "reason": admit.reason or "max_peers"},
                wait=True,
            )
            peer.close()
            return
        ok = await self._do_handshake(peer, initiator=False)
        if not ok:
            peer.close()
            return
        if self._is_banned(self._peer_key(peer)):
            peer.close()
            return
        reg = self.peer_manager.register(
            peer,
            inbound=True,
            local_node_id=self._local_node_id(),
        )
        if not reg.allowed:
            peer.close()
            return
        print(f"[P2P] Connected (libp2p): {peer}")
        self._bind_bootstraps_for_peer(peer)
        self._schedule_sync(peer)
        await self._message_loop(peer)

    async def _native_accept_loop(self) -> None:
        """Accept loop for P2PNativeListener (v1.3.90).

        ``accept`` runs in a worker thread (may block until listener close /
        accept timeout). Always re-check ``_running`` so ``stop()`` can unwind
        without waiting for a stuck gather forever.
        """
        while self._running and self._native_listener is not None:
            listener = self._native_listener
            try:
                out = await asyncio.to_thread(listener.accept)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running or self._native_listener is None:
                    break
                self._native_accept_errors = int(self._native_accept_errors or 0) + 1
                logger.warning("[P2P] native accept error: %s", exc)
                await asyncio.sleep(0.2)
                continue
            if not self._running or self._native_listener is None:
                break
            if not isinstance(out, dict) or not out.get("ok"):
                self._native_accept_errors = int(self._native_accept_errors or 0) + 1
                await asyncio.sleep(0.05)
                continue
            conn = out.get("conn")
            if conn is None:
                continue
            self._native_accept_total = int(self._native_accept_total or 0) + 1
            asyncio.create_task(self._handle_native_incoming(conn))

    async def _handle_native_incoming(self, native_conn) -> None:
        """Inbound peer path for native TCP conn (mirrors _handle_incoming)."""
        self._apply_native_io_timeout(native_conn)
        qmax, dto = self._peer_send_queue_params()
        peer = PeerConnection(
            None, None, send_queue_max=qmax, drain_timeout_sec=dto, native_conn=native_conn
        )
        self._attach_peer_hooks(peer)
        if self._is_addr_banned(peer.host, peer.port):
            peer.close()
            return
        admit = self.peer_manager.allow_inbound(str(peer.host or ""))
        if not admit.allowed:
            self._handshake_rejects = int(self._handshake_rejects or 0) + 1
            await peer.send(
                MSG_HANDSHAKE_ACK,
                {"accepted": False, "reason": admit.reason or "max_peers"},
                wait=True,
            )
            peer.close()
            return
        ok = await self._do_handshake(peer, initiator=False)
        if not ok:
            peer.close()
            return
        if self._is_banned(self._peer_key(peer)):
            peer.close()
            return

        reg = self.peer_manager.register(
            peer,
            inbound=True,
            local_node_id=self._local_node_id(),
        )
        if not reg.allowed:
            # Canonical direction already live — keep mesh peer, drop this socket.
            if reg.reason in ("duplicate_peer", "duplicate_noncanonical"):
                peer.close()
                return
            peer.close()
            return
        print(f"[P2P] Connected (native): {peer}")
        self._bind_bootstraps_for_peer(peer)
        self._schedule_sync(peer)
        await self._message_loop(peer)

    def stop(self):
        self._running = False
        self._libp2p_listening = False
        if self._server:
            self._server.close()
        if self._native_listener is not None:
            try:
                self._native_listener.close()
            except Exception as exc:
                logger.debug("[P2P] native listener close failed: %s", exc)
            self._native_listener = None
        ds = getattr(self, "_dual_stack", None)
        if ds is not None:
            try:
                ds.libp2p.close()
            except Exception as exc:
                logger.debug("[P2P] libp2p adapter close failed: %s", exc)
        self._libp2p_sessions.clear()
        self.peer_manager.clear(close=True)
        print("[P2P] Stopped")

    def _attach_peer_hooks(self, peer: PeerConnection) -> None:
        """Wire peer callbacks into node counters."""
        peer._on_send_fail = self._bump_peer_send_fail
        peer._on_send_drop = self._bump_outbound_drop
        peer._on_egress_reject = self._bump_egress_reject
        peer._egress_max_bytes = _max_p2p_line_bytes(self.config)
        peer._native_auto_pong = bool(getattr(self, "_native_auto_pong", False))
        peer._native_read_batch = int(getattr(self, "_native_read_batch", 8) or 8)
        peer._native_write_batch = int(getattr(self, "_native_write_batch", 8) or 8)
        peer._read_chunk = int(getattr(self, "_native_read_chunk", 65536) or 65536)
        peer._native_io_timeout_ms = int(
            getattr(self, "_native_io_timeout_ms", 30000) or 30000
        )
        peer._native_poll_timeout_ms = int(
            getattr(self, "_native_poll_timeout_ms", 100) or 100
        )
        peer._native_message_loop_shell = bool(
            getattr(self, "_native_message_loop_shell", False)
        )
        peer._transport_adapter = getattr(self, "transport_adapter", None)
        # Dual-stack: start in auto mode; peer codec is learned from first inbound.
        peer._wire_codec = None
        if self._use_native_egress:
            peer._rl_table = self._rl_table
            peer._rl_lock = self._rl_lock
            peer._use_egress_prepare = hasattr(native, "p2p_egress_prepare") or (
                peer._transport_adapter is not None
            )
        else:
            peer._rl_lock = self._rl_lock

    def _apply_native_io_timeout(self, native_conn) -> None:
        """v1.3.102: apply configured SO_RCV/SNDTIMEO on a native conn."""
        if native_conn is None or not hasattr(native_conn, "set_timeout_ms"):
            return
        ms = int(getattr(self, "_native_io_timeout_ms", 30000) or 30000)
        try:
            native_conn.set_timeout_ms(ms)
        except Exception as exc:
            logger.warning("[P2P] native set_timeout_ms failed: %s", exc)

    def _bump_peer_send_fail(self) -> None:
        self._peer_send_fail = int(self._peer_send_fail or 0) + 1

    def _bump_outbound_drop(self) -> None:
        """Aggregate per-peer send-queue drops (v1.3.72)."""
        self._outbound_drops = int(self._outbound_drops or 0) + 1

    def _bump_egress_reject(self) -> None:
        """Outbound bandwidth rejects (v1.3.85)."""
        self._egress_rejects = int(self._egress_rejects or 0) + 1

    def _peer_send_queue_params(self) -> tuple[int, float]:
        qmax = int(getattr(self.config, "p2p_send_queue_max", 256) or 256)
        dto = float(getattr(self.config, "p2p_drain_timeout_sec", 5.0) or 5.0)
        return max(8, qmax), max(0.5, dto)

    def _new_peer_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> PeerConnection:
        qmax, dto = self._peer_send_queue_params()
        return PeerConnection(
            reader, writer, send_queue_max=qmax, drain_timeout_sec=dto
        )

    def _record_broadcast_results(self, results, *, kind: str = "broadcast") -> None:
        """Count False/Exception outcomes from gather(return_exceptions=True)."""
        fails = 0
        for item in results or ():
            if item is False or isinstance(item, BaseException):
                fails += 1
        if fails:
            self._broadcast_fail = int(self._broadcast_fail or 0) + fails
            logger.warning(
                "[P2P] %s partial failure: %s/%s sends failed",
                kind,
                fails,
                len(results),
            )

    # ── Входящие соединения ──────────────────────────────────────────────────

    async def _handle_incoming(self, reader: asyncio.StreamReader,
                                writer: asyncio.StreamWriter):
        peer = self._new_peer_connection(reader, writer)
        self._attach_peer_hooks(peer)
        peer_addr = writer.get_extra_info("peername")
        if peer_addr and len(peer_addr) >= 2:
            peer.host = peer_addr[0]
            peer.port = int(peer_addr[1] or 0)
        if self._is_addr_banned(peer.host, peer.port):
            peer.close()
            return
        logger.debug(f"[P2P] Incoming from {peer_addr}")

        admit = self.peer_manager.allow_inbound(str(peer.host or ""))
        if not admit.allowed:
            self._handshake_rejects = int(self._handshake_rejects or 0) + 1
            await peer.send(
                MSG_HANDSHAKE_ACK,
                {"accepted": False, "reason": admit.reason or "max_peers"},
                wait=True,
            )
            peer.close()
            return

        # Handshake
        ok = await self._do_handshake(peer, initiator=False)
        if not ok:
            peer.close()
            return
        if self._is_banned(self._peer_key(peer)):
            peer.close()
            return

        reg = self.peer_manager.register(
            peer,
            inbound=True,
            local_node_id=self._local_node_id(),
        )
        if not reg.allowed:
            # Canonical direction already live — keep mesh peer, drop this socket.
            if reg.reason in ("duplicate_peer", "duplicate_noncanonical"):
                peer.close()
                return
            peer.close()
            return
        print(f"[P2P] Connected: {peer}")
        self._bind_bootstraps_for_peer(peer)
        self._schedule_sync(peer)
        await self._message_loop(peer)

    # ── Исходящие соединения ─────────────────────────────────────────────────

    async def connect_peer(self, host: str, port: int) -> bool:
        """Подключается к пиру по адресу."""
        addr = f"{host}:{port}"
        # Не подключаться к самому себе
        if port == self.config.p2p_port and host in ("127.0.0.1", "localhost", "0.0.0.0"):
            return False
        if self._use_libp2p_transport and self._host_looks_like_libp2p_peer_id(host):
            logger.debug(
                "[P2P] skip libp2p dial: host looks like PeerId, not DNS (%s)",
                host[:24],
            )
            return False
        if self._is_addr_banned(host, port):
            return False
        self._prune_stale_peers()
        # v1.3.72/77: outbound max_peers (inbound already enforced at handshake)
        admit = self.peer_manager.allow_outbound()
        if not admit.allowed:
            logger.debug("[P2P] outbound connect skipped: %s", admit.reason)
            return False
        # Не дублировать соединения
        if self.peer_manager.has_active_endpoint(host, port):
            return False
        if self._bootstrap_already_covered(host, port):
            return False

        try:
            if self._use_libp2p_transport:
                from network.transport.errors import TransportCapabilityError
                from network.transport.types import PeerEndpoint

                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._dual_stack.dial,
                            PeerEndpoint(host=str(host), port=int(port)),
                        ),
                        timeout=20,
                    )
                except TransportCapabilityError as exc:
                    logger.debug("[P2P] libp2p dial failed %s: %s", addr, exc)
                    return False
                handle = dict((result or {}).get("handle") or {})
                remote = str(handle.get("peer_id") or "").strip()
                if not remote or not handle.get("connected"):
                    logger.debug("[P2P] libp2p dial incomplete %s handle=%s", addr, handle)
                    return False
                existing = self._libp2p_sessions.get(remote)
                if existing is not None and existing.peer_id and existing.peer_id in self.peers:
                    return True
                peer = self._new_libp2p_peer(host, int(port), remote)
                if peer.peer_id and peer.peer_id in self.peers:
                    return True
                if getattr(peer, "_libp2p_inbound_handler", False):
                    return bool(peer.peer_id and peer.peer_id in self.peers)
                if str(getattr(peer, "_libp2p_role", "") or "") == "outbound":
                    return bool(peer.peer_id and peer.peer_id in self.peers)
                local_id = str(self._dual_stack.libp2p.peer_id or "")
                # One Absolute handshake initiator per Noise session (lexicographic PeerId).
                if local_id and remote and local_id > remote:
                    peer._libp2p_role = "passive"
                    self._attach_peer_hooks(peer)
                    peer.host = host
                    peer.port = int(port)
                    peer.dial_target = addr
                    for _ in range(50):
                        if peer.peer_id and peer.peer_id in self.peers:
                            return True
                        await asyncio.sleep(0.1)
                    return bool(peer.peer_id and peer.peer_id in self.peers)
                peer._libp2p_role = "outbound"
                self._native_connect_total = int(self._native_connect_total or 0) + 1
            elif self._use_native_transport and hasattr(native, "p2p_native_connect"):
                max_bytes = _max_p2p_line_bytes(self.config)
                tls_args = {}
                if self._native_tls:
                    tls_args = {
                        "cert_path": str(
                            getattr(self.config, "p2p_tls_cert_path", "") or ""
                        ),
                        "key_path": str(
                            getattr(self.config, "p2p_tls_key_path", "") or ""
                        ),
                        "ca_path": str(getattr(self.config, "p2p_tls_ca_path", "") or ""),
                    }
                io_ms = int(getattr(self, "_native_io_timeout_ms", 30000) or 30000)
                connect_ms = min(io_ms, 15_000)
                nconn = await asyncio.wait_for(
                    asyncio.to_thread(
                        lambda: native.p2p_native_connect(
                            host,
                            int(port),
                            int(max_bytes),
                            int(connect_ms),
                            **tls_args,
                        )
                    ),
                    timeout=max(1.0, connect_ms / 1000.0) + 5.0,
                )
                self._apply_native_io_timeout(nconn)
                qmax, dto = self._peer_send_queue_params()
                peer = PeerConnection(
                    None,
                    None,
                    send_queue_max=qmax,
                    drain_timeout_sec=dto,
                    native_conn=nconn,
                )
                self._native_connect_total = int(self._native_connect_total or 0) + 1
            else:
                client_ssl = build_p2p_client_ssl_context(self.config)
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port, ssl=client_ssl),
                    timeout=10,
                )
                peer = self._new_peer_connection(reader, writer)
            self._attach_peer_hooks(peer)
            peer.host = host
            peer.port = port
            peer.dial_target = addr

            ok = await self._do_handshake(peer, initiator=True)
            if not ok:
                peer.close()
                return False
            if self._is_banned(self._peer_key(peer)):
                peer.close()
                return False

            dial_addr = self._normalize_dial_addr(addr)
            # Re-check after handshake (race with inbound accepts).
            admit = self.peer_manager.allow_outbound()
            if not admit.allowed:
                # If the peer already registered via inbound, treat as success.
                if peer.peer_id and peer.peer_id in self.peers:
                    self._remember_addr(addr)
                    self._bind_bootstrap_peer(dial_addr, peer.peer_id)
                    peer.close()
                    return True
                peer.close()
                return False

            reg = self.peer_manager.register(
                peer,
                inbound=False,
                local_node_id=self._local_node_id(),
            )
            if not reg.allowed:
                self._remember_addr(addr)
                # Mesh already has this peer_id (canonical inbound or race winner).
                if reg.reason in ("duplicate_peer", "duplicate_noncanonical"):
                    if peer.peer_id in self.peers:
                        self._bind_bootstrap_peer(dial_addr, peer.peer_id)
                        peer.close()
                        return True
                    peer.close()
                    return False
                peer.close()
                return False
            self._remember_addr(addr)
            self._bind_bootstrap_peer(dial_addr, peer.peer_id)
            self._bind_bootstraps_for_peer(peer)

            print(f"[P2P] Connected to {peer}")

            # Синхронизация если отстаём
            self._schedule_sync(peer)
            asyncio.create_task(self._message_loop(peer))
            return True

        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
            logger.debug(f"[P2P] Cannot connect to {addr}: {e}")
            return False

    def _local_node_id(self) -> str:
        return str(
            getattr(self.config, "node_id", None) or f"abs-{self.config.p2p_port}"
        )

    # ── Handshake ────────────────────────────────────────────────────────────

    async def _do_handshake(self, peer: PeerConnection, initiator: bool) -> bool:
        our_height = self.blockchain.get_height()
        our_info = {
            "chain_id": self.config.chain_id,
            "version": self.config.node_version,
            "height": our_height,
            "head_hash": self.head() or "",
            "node_id": getattr(self.config, "node_id", f"abs-{self.config.p2p_port}"),
            "p2p_port": int(getattr(self.config, "p2p_port", 0) or 0),
        }

        # v1.3.96: native handshake I/O fuse when transport owns the socket.
        # v1.3.115: pass chain_id + TLS identity policy into Rust (skip dual Python policy).
        native_policy_applied = False
        if (
            peer._native_conn is not None
            and hasattr(peer._native_conn, "handshake_roundtrip")
        ):
            import json

            our_json = json.dumps(our_info, separators=(",", ":"), ensure_ascii=False)
            tls_on = p2p_tls_enabled(self.config)
            bind_id = bool(getattr(self.config, "p2p_tls_bind_identity", True))
            try:
                out = await asyncio.wait_for(
                    asyncio.to_thread(
                        peer._native_io_call,
                        peer._native_conn.handshake_roundtrip,
                        bool(initiator),
                        our_json,
                        int(peer._read_chunk or 65536),
                        int(self.config.chain_id),
                        bool(tls_on),
                        bool(bind_id) if tls_on else False,
                    ),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                return False
            except Exception as exc:
                logger.warning(
                    "[P2P] native handshake error from %s: %s",
                    peer.host,
                    exc,
                )
                return False
            if not isinstance(out, dict) or not out.get("ok"):
                reason = ""
                if isinstance(out, dict):
                    reason = str(out.get("reason") or "")
                self._handshake_rejects += 1
                if reason in (
                    "bad_handshake_payload",
                    "bad_handshake_head_digest",
                    "bad_handshake_height_head",
                    "chain_id_mismatch",
                    "tls_missing",
                    "tls_identity_mismatch",
                ):
                    self._strike_peer_sync(peer, reason)
                logger.warning(
                    "[P2P] native handshake reject from %s (%s)",
                    peer.host,
                    reason or "handshake_failed",
                )
                return False
            expect = MSG_HANDSHAKE_ACK if initiator else MSG_HANDSHAKE
            if out.get("type") != expect:
                return False
            ack = out.get("data", {})
            native_policy_applied = True
        elif initiator:
            await peer.send(MSG_HANDSHAKE, our_info, wait=True)
            msg = await peer.recv(self.config)
            if not msg or msg.get("type") != MSG_HANDSHAKE_ACK:
                return False
            ack = msg.get("data", {})
        else:
            msg = await peer.recv(self.config)
            if not msg or msg.get("type") != MSG_HANDSHAKE:
                return False
            ack = msg.get("data", {})
            await peer.send(MSG_HANDSHAKE_ACK, our_info, wait=True)

        hs = native.validate_p2p_handshake_payload(ack)
        if not hs:
            self._handshake_rejects += 1
            self._strike_peer_sync(peer, "bad_handshake_payload")
            return False
        if hs.get("accepted") is False:
            self._handshake_rejects += 1
            return False

        # v1.3.129: head digest + soft height binding (native path also fused).
        hs_reason = native.verify_p2p_handshake_head_semantics(ack)
        if hs_reason:
            self._handshake_rejects += 1
            self._handshake_head_rejects_total = int(
                self._handshake_head_rejects_total or 0
            ) + 1
            self._strike_peer_sync(peer, str(hs_reason))
            return False

        # Проверяем совместимость (native path already fused chain_id + TLS identity).
        if not native_policy_applied and hs.get("chain_id") != self.config.chain_id:
            self._handshake_rejects += 1
            self._strike_peer_sync(peer, "chain_id_mismatch")
            print(
                f"[P2P] Rejected {peer.host}:{peer.port}: chain_id mismatch "
                f"(remote={hs.get('chain_id')} local={self.config.chain_id}). "
                f"Use the same node.json on both nodes."
            )
            return False

        claimed_id = str(hs.get("node_id") or "").strip() or f"{peer.host}:{peer.port}"
        if p2p_tls_enabled(self.config):
            if peer.writer is not None:
                tls_meta = extract_peer_tls_meta(peer.writer)
            elif peer._native_conn is not None and bool(
                getattr(peer._native_conn, "tls", False)
            ):
                # Native rustls path: fingerprint + CN/SAN identities (v1.3.97).
                ids = list(getattr(peer._native_conn, "peer_cert_identities", []) or [])
                tls_meta = {
                    "ssl": True,
                    "fingerprint_sha256": str(
                        getattr(peer._native_conn, "peer_cert_sha256", "") or ""
                    ),
                    "identities": ids,
                }
            else:
                tls_meta = {"ssl": False, "fingerprint_sha256": "", "identities": []}
            identities = set(tls_meta.get("identities") or [])
            fp = str(tls_meta.get("fingerprint_sha256") or "")
            peer.tls_fingerprint = fp
            peer.tls_identities = sorted(identities)
            bind_id = bool(getattr(self.config, "p2p_tls_bind_identity", True))
            if not native_policy_applied:
                if not tls_meta.get("ssl"):
                    self._handshake_rejects += 1
                    self._strike_peer_sync(peer, "tls_missing")
                    print(f"[P2P] Rejected {peer.host}:{peer.port}: TLS required but no ssl_object")
                    return False
                if bind_id:
                    if not identities or not handshake_node_id_matches_cert(claimed_id, identities):
                        self._handshake_rejects += 1
                        self._strike_peer_sync(peer, "tls_identity_mismatch")
                        print(
                            f"[P2P] Rejected {peer.host}:{peer.port}: handshake node_id "
                            f"{claimed_id!r} not in peer cert CN/SAN {sorted(identities)}"
                        )
                        return False
            allow = fingerprint_allowlist(self.config)
            if allow and fp.lower() not in allow:
                self._handshake_rejects += 1
                self._strike_peer_sync(peer, "tls_fingerprint_denied")
                print(
                    f"[P2P] Rejected {peer.host}:{peer.port}: cert fingerprint "
                    f"not in P2P_TLS_PEER_FINGERPRINTS allowlist"
                )
                return False
            # v1.3.133: per-seed bootstrap pin (addr → fingerprint[/node_id])
            pin_reason = self._bootstrap_pin_reject_reason(peer, claimed_id, fp)
            if pin_reason:
                self._handshake_rejects += 1
                self._bootstrap_pin_rejects_total = int(
                    self._bootstrap_pin_rejects_total or 0
                ) + 1
                self._strike_peer_sync(peer, pin_reason)
                print(
                    f"[P2P] Rejected {peer.host}:{peer.port}: bootstrap pin "
                    f"{pin_reason} (P2P_BOOTSTRAP_PINS)"
                )
                return False

        peer.peer_id = claimed_id
        peer.chain_id = hs.get("chain_id", 0)
        # v1.3.135: soft handshake height-ahead ownership (same window as status/new_block).
        # Height 0 is valid genesis — never coerce via ``or 0`` after a missing check.
        if isinstance(hs, dict) and "height" in hs and hs.get("height") is not None:
            try:
                hs_h = int(hs.get("height"))
            except (TypeError, ValueError):
                hs_h = -1
        else:
            hs_h = -1
        hs_head = str(hs.get("head_hash") or "").strip()
        owned_h, capped = self._cap_claimed_peer_height(max(hs_h, 0) if hs_h >= 0 else 0)
        if hs_h < 0:
            owned_h = -1
        if capped:
            self._handshake_height_cap_total = int(
                self._handshake_height_cap_total or 0
            ) + 1
            hs_head = ""  # do not install fantasy head with capped height
        # v1.3.166: head without height refused when local tip > 0.
        head_only_reason = self._handshake_head_without_height_refuse_reason(
            hs_head, owned_h, int(our_height if our_height is not None else 0)
        )
        if head_only_reason:
            self._handshake_head_without_height_total = int(
                getattr(self, "_handshake_head_without_height_total", 0) or 0
            ) + 1
            self._handshake_rejects += 1
            self._strike_peer_sync(peer, head_only_reason)
            print(
                f"[P2P] Rejected {peer.host}:{peer.port}: {head_only_reason}"
            )
            return False
        # v1.3.155: known local head ⇒ claimed height must match (soft ownership).
        if hs_head and owned_h >= 0:
            bind_reason = self._status_head_height_refuse_reason(
                hs_head, owned_h, reason="handshake_head_height_mismatch"
            )
            if bind_reason:
                self._status_head_height_mismatch_total = int(
                    getattr(self, "_status_head_height_mismatch_total", 0) or 0
                ) + 1
                self._handshake_rejects += 1
                self._strike_peer_sync(peer, bind_reason)
                print(
                    f"[P2P] Rejected {peer.host}:{peer.port}: {bind_reason}"
                )
                return False
        peer.height = max(0, int(owned_h)) if int(owned_h) >= 0 else 0
        # v1.3.159: capped height clears fantasy head (do not keep prior peer.head).
        if capped and bool(getattr(self.config, "p2p_height_cap_clear_head", True)):
            peer.head = ""
        else:
            peer.head = hs_head or peer.head
        peer.listen_port = int(hs.get("p2p_port", 0) or peer.port or 0)
        if peer.host and peer.listen_port:
            self._remember_addr(f"{peer.host}:{peer.listen_port}")
        await peer.send(MSG_STATUS, {
            "height": our_height,
            "head_hash": self.head() or "",
        })
        # v1.3.103: native mid-session handshake gate
        if peer._native_conn is not None and hasattr(
            peer._native_conn, "set_session_established"
        ):
            try:
                peer._native_io_call(peer._native_conn.set_session_established, True)
            except Exception as exc:
                logger.debug("[P2P] set_session_established failed: %s", exc)
        return True

    # ── Цикл сообщений ───────────────────────────────────────────────────────

    async def _message_loop(self, peer: PeerConnection):
        """Основной цикл чтения сообщений от пира."""
        use_ingress = bool(self._use_native_ingress and self._rl_table is not None)
        use_shell = bool(
            getattr(self, "_native_message_loop_shell", False)
            and peer._native_conn is not None
            and hasattr(peer._native_conn, "read_message_loop_events")
        )
        try:
            while self._running and self.peers.get(peer.peer_id) is peer:
                if use_shell:
                    # v1.3.116: ordered native shell events (dispatch/strike/keepalive).
                    # Handlers + strike/ban tables stay Python — not full loop ownership.
                    try:
                        events = await peer.recv_loop_events(
                            self.config,
                            rl_table=self._rl_table if use_ingress else None,
                            peer_key=self._peer_key(peer),
                            use_ingress=use_ingress,
                            mempool_solicit_armed=self._mempool_solicit_armed_for(peer),
                        )
                    except asyncio.TimeoutError:
                        continue
                    for ev in events:
                        if not self._running or self.peers.get(peer.peer_id) is not peer:
                            break
                        action = str((ev or {}).get("action") or "")
                        if action == "eof":
                            return
                        if action in ("idle",):
                            continue
                        if action == "keepalive":
                            peer.touch()
                            continue
                        if action == "strike":
                            reason = str((ev or {}).get("reason") or "unknown")
                            self._native_message_loop_strikes_total = int(
                                self._native_message_loop_strikes_total or 0
                            ) + 1
                            if reason in (
                                "bad_attestation_identity",
                                "bad_attestation_sig",
                            ):
                                self._attestation_semantic_rejects_total = int(
                                    self._attestation_semantic_rejects_total or 0
                                ) + 1
                            if reason in (
                                "missing_tx_signature",
                                "missing_tx_public_key",
                                "bad_tx_signature",
                            ):
                                # Covers new_tx + mempool batch signature semantic rejects.
                                self._tx_semantic_rejects_total = int(
                                    self._tx_semantic_rejects_total or 0
                                ) + 1
                            if reason == "unsolicited_mempool":
                                # v1.3.144: native shell cheap refuse (no batch ECDSA).
                                self._unsolicited_mempool_rejects_total = int(
                                    self._unsolicited_mempool_rejects_total or 0
                                ) + 1
                            if reason == "bad_block_hash":
                                self._block_semantic_rejects_total = int(
                                    self._block_semantic_rejects_total or 0
                                ) + 1
                            if reason == "bad_state_root_digest":
                                self._state_root_semantic_rejects_total = int(
                                    self._state_root_semantic_rejects_total or 0
                                ) + 1
                            if reason == "bad_status_head_digest":
                                self._status_semantic_rejects_total = int(
                                    self._status_semantic_rejects_total or 0
                                ) + 1
                            if reason == "mid_session_handshake":
                                self._handshake_rejects = int(
                                    self._handshake_rejects or 0
                                ) + 1
                                logger.warning(
                                    "[P2P] mid-session handshake (native shell) from %s",
                                    peer.peer_id or self._peer_key(peer),
                                )
                            if self._strike_peer_sync(peer, reason):
                                return
                            continue
                        if action == "dispatch":
                            msg = {
                                "type": (ev or {}).get("type"),
                                "data": (ev or {}).get("data"),
                            }
                            peer.touch()
                            self._native_message_loop_dispatch_total = int(
                                self._native_message_loop_dispatch_total or 0
                            ) + 1
                            if use_ingress:
                                if not self._class_rate_ok(
                                    peer.peer_id, msg.get("type")
                                ):
                                    if self._strike_peer_sync(
                                        peer, "rate_limit_class_exceeded"
                                    ):
                                        return
                                    continue
                            elif not self._rate_limit_ok(
                                peer.peer_id, msg.get("type")
                            ):
                                if self._strike_peer_sync(peer, "rate_limit_exceeded"):
                                    return
                                continue
                            await self._handle_message(peer, msg)
                            continue
                        logger.debug(
                            "[P2P] unknown loop-shell action %r from %s",
                            action,
                            peer.peer_id or self._peer_key(peer),
                        )
                    continue

                msg = await peer.recv(
                    self.config,
                    rl_table=self._rl_table if use_ingress else None,
                    peer_key=self._peer_key(peer),
                    use_ingress=use_ingress,
                )
                if msg is None:
                    break
                if isinstance(msg, WireReject):
                    reason = str(msg.reason or "")
                    if reason == "mid_session_handshake":
                        self._handshake_rejects = int(self._handshake_rejects or 0) + 1
                        logger.warning(
                            "[P2P] mid-session handshake (native) from %s",
                            peer.peer_id or self._peer_key(peer),
                        )
                    if self._strike_peer_sync(peer, msg.reason):
                        break
                    continue
                if msg.get("type") == MSG_IDLE:
                    continue
                peer.touch()
                # Native ingress already applied primary + exempt. Class quotas
                # still run so attest/tx/header floods cannot share one window.
                if use_ingress:
                    if not self._class_rate_ok(peer.peer_id, msg.get("type")):
                        if self._strike_peer_sync(peer, "rate_limit_class_exceeded"):
                            break
                        continue
                elif not self._rate_limit_ok(peer.peer_id, msg.get("type")):
                    if self._strike_peer_sync(peer, "rate_limit_exceeded"):
                        break
                    continue
                await self._handle_message(peer, msg)
        finally:
            self._remove_peer(peer.peer_id, peer)

    def _peer_key(self, peer: PeerConnection) -> str:
        return self.peer_manager.peer_key(peer)

    def _is_banned(self, key: str) -> bool:
        return self.peer_manager.is_banned(key)

    def _is_addr_banned(self, host: str, port: int) -> bool:
        return self.peer_manager.is_addr_banned(host, port)

    def _strike_peer_sync(self, peer: PeerConnection, reason: str) -> bool:
        """Record abuse strike; return True if peer should be disconnected (banned).

        Soft-refuse reasons (solicit races / disabled gossip) increment metrics and
        are logged, but must **not** ban mesh peers — otherwise prod mTLS nodes
        mutually ban within seconds (validator_register + unsolicited_*).
        """
        why = str(reason or "")
        # Soft refuse: keep fail-closed message drop (caller already refused) without ban.
        soft = getattr(self, "_SOFT_REFUSE_STRIKE_REASONS", None)
        if soft is None:
            soft = frozenset(
                {
                    "validator_register_disabled",
                    "unsolicited_mempool",
                    "unsolicited_block",
                    "unsolicited_blocks",
                    "unsolicited_peers",
                    "unsolicited_state_root_response",
                    "unsolicited_state_root",
                    "tip_duplicate",
                    # Height/hash race under catch-up — drop attestation, do not ban mesh.
                    "attestation_local_height_mismatch",
                    # Sync/catch-up bursts trip the token bucket; drop msgs, do not ban mesh.
                    "rate_limit_exceeded",
                    "rate_limit_class_exceeded",
                    "exempt_rate_exceeded",
                    "bandwidth_exceeded",
                    "rate_limited",
                    # Catch-up / tip races under partial mesh — drop tip, do not ban.
                    "tip_unknown_parent",
                }
            )
            self._SOFT_REFUSE_STRIKE_REASONS = soft
        # Transient TLS/EOF tears on mesh reconnects must not escalate to bans.
        if why in soft or why.startswith("p2p_transport_io:"):
            self._soft_refuse_total = int(getattr(self, "_soft_refuse_total", 0) or 0) + 1
            # Keep security counters honest (rate_limit_drops / shape_rejects) without
            # PeerManager strike escalation toward ban.
            bump = getattr(self.peer_manager, "note_shape_reject", None)
            if bump is None:
                bump = getattr(self.peer_manager, "_bump_shape", None)
            if bump is not None:
                try:
                    bump(why or "unknown")
                except Exception as exc:
                    logger.debug("[P2P] soft-refuse shape counter failed: %s", exc)
            logger.info(
                "[P2P] soft-refuse %s from %s (no ban; mesh-safe)",
                why[:80],
                (getattr(peer, "peer_id", None) or "?")[:16],
            )
            return False
        return self.peer_manager.strike(peer, reason)

    def _peer_strike_count(self, peer: PeerConnection) -> int:
        return self.peer_manager.strike_count(peer)

    def _note_peer_import_fail(self, peer: Optional[PeerConnection]) -> None:
        """v1.3.145: attribute failed imports to the sourcing peer for score honesty."""
        self.peer_manager.note_import_fail(peer)

    def _score_peer(
        self,
        peer: PeerConnection,
        *,
        local_height: int,
        health_timeout: float,
        now: Optional[float] = None,
    ) -> int:
        """Compose soft peer score including strike/import quality (v1.3.145)."""
        return self.peer_manager.score(
            peer,
            local_height=local_height,
            health_timeout=health_timeout,
            now=now,
        )

    def _exempt_rate_ok(self, peer_id: str) -> bool:
        """Secondary per-peer budget for RATE_LIMIT_EXEMPT_TYPES (v1.3.72).

        Primary rate limit exempts sync/tx gossip so catch-up works; this ceiling
        still bounds get_blocks/new_tx floods. 0 = disabled.
        Prefer native table.exempt_rate_ok when available (v1.3.77).
        """
        if self._rl_table is not None and hasattr(self._rl_table, "exempt_rate_ok"):
            with self._rl_lock:
                ok = bool(
                    self._rl_table.exempt_rate_ok(str(peer_id or ""), float(time.time()))
                )
            if not ok:
                logger.warning(
                    "[P2P] exempt-type rate exceeded for %s (%s/s)",
                    peer_id,
                    int(getattr(self.config, "p2p_exempt_messages_per_sec", 0) or 0),
                )
            return ok
        limit = int(getattr(self.config, "p2p_exempt_messages_per_sec", 0) or 0)
        if limit <= 0 or not peer_id:
            return True
        now = time.time()
        count, start = self._peer_exempt_windows.get(peer_id, (0, now))
        if now - start >= 1.0:
            count, start = 0, now
        count += 1
        self._peer_exempt_windows[peer_id] = (count, start)
        if count > limit:
            logger.warning(
                "[P2P] exempt-type rate exceeded for %s (%s/s)",
                peer_id,
                limit,
            )
            return False
        return True

    def _rate_limit_class_limit(self, msg_type: Optional[str]) -> tuple[str, int]:
        """Map wire type to class name + per-sec cap. Empty class = no class quota."""
        kind = str(msg_type or "")
        if kind == MSG_ATTESTATION:
            return (
                RATE_LIMIT_CLASS_ATTEST,
                int(getattr(self.config, "p2p_attest_messages_per_sec", 0) or 0),
            )
        if kind == MSG_NEW_TX:
            return (
                RATE_LIMIT_CLASS_TX,
                int(getattr(self.config, "p2p_tx_messages_per_sec", 0) or 0),
            )
        if kind == MSG_NEW_BLOCK:
            return (
                RATE_LIMIT_CLASS_BLOCK,
                int(
                    getattr(self.config, "p2p_block_announce_messages_per_sec", 0)
                    or 0
                ),
            )
        return ("", 0)

    def _class_rate_ok(self, peer_id: str, msg_type: Optional[str] = None) -> bool:
        """Per-peer class token bucket. Runs even when native ingress already admitted."""
        cls, limit = self._rate_limit_class_limit(msg_type)
        if not cls or limit <= 0 or not peer_id:
            return True
        now = time.time()
        key = f"{peer_id}\0{cls}"
        count, start = self._peer_class_windows.get(key, (0, now))
        if now - start >= 1.0:
            count, start = 0, now
        count += 1
        self._peer_class_windows[key] = (count, start)
        if count > limit:
            logger.warning(
                "[P2P] class rate exceeded for %s class=%s (%s/s)",
                peer_id,
                cls,
                limit,
            )
            return False
        return True

    def _rate_limit_ok(self, peer_id: str, msg_type: Optional[str] = None) -> bool:
        """Per-peer message rate limit (0 = disabled). Sync/housekeeping types exempt
        from primary budget; still subject to p2p_exempt_messages_per_sec (v1.3.72).
        Class quotas (attest/tx/block announce) apply first.
        """
        if not self._class_rate_ok(peer_id, msg_type):
            return False
        if msg_type in RATE_LIMIT_EXEMPT_TYPES and not self._exempt_rate_ok(peer_id):
            return False
        if self._rl_table is not None:
            with self._rl_lock:
                ok = bool(
                    self._rl_table.rate_ok(
                        str(peer_id or ""),
                        str(msg_type or ""),
                        float(time.time()),
                    )
                )
            if not ok:
                logger.warning(
                    "[P2P] rate limit exceeded for %s (%s/s)",
                    peer_id,
                    int(getattr(self.config, "p2p_max_messages_per_sec", 0) or 0),
                )
            return ok
        if msg_type in RATE_LIMIT_EXEMPT_TYPES:
            return True
        limit = int(getattr(self.config, "p2p_max_messages_per_sec", 0) or 0)
        if limit <= 0 or not peer_id:
            return True
        now = time.time()
        count, start = self._peer_msg_windows.get(peer_id, (0, now))
        if now - start >= 1.0:
            count, start = 0, now
        count += 1
        self._peer_msg_windows[peer_id] = (count, start)
        if count > limit:
            logger.warning("[P2P] rate limit exceeded for %s (%s/s)", peer_id, limit)
            return False
        return True

    async def _handle_message(self, peer: PeerConnection, msg: Dict):
        msg_type = msg.get("type")
        if msg_type not in ALLOWED_WIRE_TYPES:
            if self._strike_peer_sync(peer, f"unknown_type:{msg_type}"):
                self._remove_peer(peer.peer_id, peer)
            return
        # Mid-session handshake is abuse (initial handshake uses _do_handshake recv).
        if msg_type in (MSG_HANDSHAKE, MSG_HANDSHAKE_ACK):
            self._handshake_rejects = int(self._handshake_rejects or 0) + 1
            logger.warning(
                "[P2P] mid-session %s from %s",
                msg_type,
                peer.peer_id or self._peer_key(peer),
            )
            if self._strike_peer_sync(peer, "mid_session_handshake"):
                self._remove_peer(peer.peer_id, peer)
            return
        data = msg.get("data")

        # Fail-closed shape gates before sync waiters consume the message.
        # v1.3.114: native read path already ran check_ingress_shape_gates — skip dual re-validate.
        if not getattr(self, "_use_native_transport", False):
            if msg_type == MSG_STATE_ROOT_RESPONSE:
                if not native.validate_p2p_state_root_response(data):
                    self._strike_peer_sync(peer, "bad_state_root_response")
                    return
            elif msg_type == MSG_STATE_ROOT_REQUEST:
                if native.validate_p2p_state_root_request(data) is None:
                    self._strike_peer_sync(peer, "bad_state_root_request")
                    return
            elif msg_type == MSG_NEW_BLOCK:
                if not native.validate_p2p_block_announce(data):
                    self._strike_peer_sync(peer, "bad_block_announce")
                    return
            elif msg_type == MSG_ATTESTATION:
                if not native.validate_p2p_attestation_payload(data):
                    self._strike_peer_sync(peer, "bad_attestation_shape")
                    return
            elif msg_type == MSG_STATUS:
                if native.validate_p2p_status_payload(data) is None and data is not None:
                    # Allow null/empty status keepalives; reject malformed dicts.
                    if isinstance(data, dict):
                        self._strike_peer_sync(peer, "bad_status_payload")
                        return

            elif msg_type == MSG_NEW_TX:
                if not native.validate_p2p_wire_tx(data):
                    self._strike_peer_sync(peer, "bad_wire_tx")
                    return
            elif msg_type == MSG_MEMPOOL:
                if native.validate_p2p_mempool_batch(data) is None:
                    self._strike_peer_sync(peer, "bad_mempool_batch")
                    return
            elif msg_type == MSG_GET_BLOCKS:
                if native.validate_p2p_get_blocks_payload(data) is None:
                    self._strike_peer_sync(peer, "bad_get_blocks")
                    return
            elif msg_type == MSG_GET_BLOCK:
                if native.validate_p2p_get_block(data) is None:
                    self._strike_peer_sync(peer, "bad_get_block")
                    return
            elif msg_type == MSG_GET_BLOCK_BY_HASH:
                if native.validate_p2p_get_block_by_hash(data) is None:
                    self._strike_peer_sync(peer, "bad_get_block_by_hash")
                    return
            elif msg_type == MSG_BLOCKS:
                if native.validate_p2p_blocks_batch(data) is None:
                    self._strike_peer_sync(peer, "bad_blocks_batch")
                    return
            elif msg_type == MSG_BLOCK:
                # null/None = not found; non-null must match block announce shape
                if data is not None and native.validate_p2p_block_announce(data) is None:
                    self._strike_peer_sync(peer, "bad_block_payload")
                    return
            elif msg_type == MSG_PEERS:
                if native.validate_p2p_peers_list(data) is None:
                    self._strike_peer_sync(peer, "bad_peers_list")
                    return
            elif msg_type == MSG_VALIDATOR_REGISTER:
                if native.validate_p2p_validator_register(data) is None:
                    self._strike_peer_sync(peer, "bad_validator_register")
                    return
            elif msg_type == MSG_CROSS_SHARD_TX:
                if native.validate_p2p_cross_shard_tx(data) is None:
                    self._strike_peer_sync(peer, "bad_cross_shard_tx")
                    return
            elif msg_type == MSG_CROSS_SHARD_ACK:
                if native.validate_p2p_cross_shard_ack(data) is None:
                    self._strike_peer_sync(peer, "bad_cross_shard_ack")
                    return
            elif msg_type == MSG_SHARD_MIGRATION:
                if native.validate_p2p_shard_migration(data) is None:
                    self._strike_peer_sync(peer, "bad_shard_migration")
                    return
            elif msg_type in (MSG_GET_MEMPOOL, MSG_GET_PEERS, MSG_PING, MSG_PONG):
                if not _housekeeping_payload_ok(msg_type, data):
                    if self._strike_peer_sync(peer, f"bad_{msg_type}_payload"):
                        self._remove_peer(peer.peer_id, peer)
                    return

        # ADR 0003 C/D: thin handoff — hub owns waiter state; dispatcher stays unaware.
        waiter_result = self.solicit_hub.fulfill_or_reject(
            peer,
            str(msg_type or ""),
            data,
            msg if isinstance(msg, dict) else {"type": msg_type, "data": data},
            strike=self._strike_peer_sync,
            bump=self.bump_counter,
        )
        if waiter_result.consumed:
            # Timed-out waiter still occupies the hub until `finally: clear()`.
            # fulfill_or_reject consumes as late_state_root and used to skip
            # stash, so the 0.4s grace in `_wait_peer_response` always missed.
            if (
                str(msg_type or "") == MSG_STATE_ROOT_RESPONSE
                and str(getattr(waiter_result, "detail", "") or "") == "late_state_root"
            ):
                self._stash_late_state_root(peer, data)
            return
        if str(msg_type or "") == MSG_STATE_ROOT_RESPONSE and self._stash_late_state_root(
            peer, data
        ):
            return

        # ADR 0002 Step D: application type routing via Handler Registry.
        from network.p2p_dispatch import DispatchOutcome

        outcome = await self.dispatcher.dispatch(self, peer, msg_type, data)
        if outcome is DispatchOutcome.UNHANDLED:
            if self._strike_peer_sync(peer, f"unhandled_type:{msg_type}"):
                self._remove_peer(peer.peer_id, peer)

    async def _handle_validator_register(self, peer: PeerConnection, data: Dict):
        """Register peer validator in local consensus when announced.

        v1.3.65: unauthenticated P2P registration is blocked in prod /
        require_native_crypto — stake identity must come from local/manifest path.
        """
        mode = str(getattr(self.config, "deployment_mode", "dev") or "dev").lower()
        require_native = bool(getattr(self.config, "require_native_crypto", False))
        if mode in ("prod", "production", "staging") or require_native:
            logger.warning(
                "[P2P] rejecting unauthenticated validator_register from %s (prod fail-closed)",
                (peer.peer_id or "?")[:12],
            )
            self._strike_peer_sync(peer, "validator_register_disabled")
            return
        parsed = native.validate_p2p_validator_register(data)
        if not parsed:
            self._strike_peer_sync(peer, "bad_validator_register")
            return
        address = str(parsed.get("address") or "")
        stake = float(parsed.get("stake", 0) or 0)
        if not address or not self._consensus:
            return
        vals = self.blockchain.db.get_validators(active_only=False) or []
        known = {v["address"].lower() for v in vals}
        if address.lower() in known:
            return
        if hasattr(self._consensus, "add_validator"):
            if self._consensus.add_validator(address, stake):
                print(f"[P2P] Registered peer validator {address[:12]}… from {peer.peer_id[:8]}")
                await self._relay_validator_register(
                    {
                        "address": address,
                        "stake": stake,
                        "node_id": str(parsed.get("node_id") or ""),
                    },
                    exclude_peer=peer.peer_id,
                )

    async def _relay_validator_register(self, payload: Dict, exclude_peer: str = ""):
        tasks = []
        for pid, peer in list(self.peers.items()):
            if pid != exclude_peer:
                tasks.append(peer.send(MSG_VALIDATOR_REGISTER, payload))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._record_broadcast_results(results, kind="validator_register")

    def announce_validator(self, address: str, stake: float) -> None:
        """Gossip local validator registration to connected peers.

        Prod/staging / require_native: no-op — stake identity is ceremony/manifest
        only. Sending here caused receivers to strike ``validator_register_disabled``
        and mutually ban the mesh.
        """
        mode = str(getattr(self.config, "deployment_mode", "dev") or "dev").lower()
        require_native = bool(getattr(self.config, "require_native_crypto", False))
        if mode in ("prod", "production", "staging") or require_native:
            return
        payload = {"address": address, "stake": stake, "node_id": f"abs-{self.config.p2p_port}"}
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self._relay_validator_register(payload), self._loop
            )

    async def _handle_attestation(self, peer: PeerConnection, data: Dict):
        """Accept signed attestation from peer and apply to local consensus."""
        if not native.validate_p2p_attestation_payload(data):
            self._strike_peer_sync(peer, "bad_attestation_shape")
            return
        vkeys = self.validator_keys
        # v1.3.65: never accept attestations without a verifier (fail-closed).
        if not vkeys or not hasattr(vkeys, "verify_attestation"):
            logger.warning(
                "[P2P] attestation rejected — verifier unavailable from %s",
                (peer.peer_id or "?")[:12],
            )
            self._strike_peer_sync(peer, "attestation_verifier_unavailable")
            return
        if not vkeys.verify_attestation(data):
            logger.warning(
                "[P2P] Invalid attestation sig/identity from %s",
                (peer.peer_id or "?")[:12],
            )
            self._strike_peer_sync(peer, "bad_attestation_sig")
            return
        get_addr = getattr(vkeys, "get_address", None)
        our = ""
        if callable(get_addr):
            try:
                our = str(get_addr() or "").strip().lower()
            except Exception as exc:
                logger.warning(
                    "[P2P] validator_keys.get_address failed; echo-drop skipped: %s",
                    exc,
                )
        claimed = str(data.get("validator") or "").strip().lower()
        if our and claimed == our:
            # Echo of our own gossip: applying it again re-emits consensus.attestation
            # and re-signs against the live tip (wrong height) → mesh flood.
            self._attestation_echo_drops_total = int(
                getattr(self, "_attestation_echo_drops_total", 0) or 0
            ) + 1
            return
        fp = self._attestation_fingerprint(data)
        if fp and self._attestation_already_seen(fp):
            self._attestation_dup_drops_total = int(
                getattr(self, "_attestation_dup_drops_total", 0) or 0
            ) + 1
            return
        # v1.3.136: soft slot/target_height ahead vs local tip — stop LMD pollution / relay DoS.
        ahead_reason = self._attestation_ahead_reject_reason(data)
        if ahead_reason:
            self._attestation_slot_ahead_rejects_total = int(
                self._attestation_slot_ahead_rejects_total or 0
            ) + 1
            self._strike_peer_sync(peer, ahead_reason)
            return
        # v1.3.137: when local block known, target_height must match header height.
        local_reason = self._attestation_local_head_reject_reason(data)
        if local_reason:
            self._attestation_local_head_rejects_total = int(
                self._attestation_local_head_rejects_total or 0
            ) + 1
            self._strike_peer_sync(peer, local_reason)
            return
        # v1.3.167: tip-height attestation must cite local tip hash.
        tip_reason = self._attestation_target_head_refuse_reason(data)
        if tip_reason:
            self._attestation_target_head_rejects_total = int(
                getattr(self, "_attestation_target_head_rejects_total", 0) or 0
            ) + 1
            self._strike_peer_sync(peer, tip_reason)
            return
        validator = data.get("validator", "")
        block_hash = data.get("target_hash", "")
        if not validator or not block_hash:
            return
        slot_raw = data.get("slot")
        slot = int(slot_raw) if slot_raw is not None else None
        consensus = self._consensus
        if consensus and hasattr(consensus, "attest"):
            if consensus.attest(validator, block_hash, slot=slot):
                await self._relay_attestation(data, exclude_peer=peer.peer_id)

    def _attestation_fingerprint(self, data: Dict) -> tuple:
        if not isinstance(data, dict):
            return ()
        try:
            slot = int(data.get("slot") or 0)
        except (TypeError, ValueError):
            slot = 0
        return (
            str(data.get("validator") or "").strip().lower(),
            slot,
            str(data.get("target_hash") or "").strip().lower(),
            str(data.get("signature") or "")[:32],
        )

    def _attestation_already_seen(self, fp: tuple) -> bool:
        """True if this attestation was already applied/relayed (echo/dup drop)."""
        if not fp or not fp[0]:
            return False
        seen = getattr(self, "_attestation_seen", None)
        if seen is None:
            self._attestation_seen = {}
            seen = self._attestation_seen
        now = time.monotonic()
        prev = seen.get(fp)
        if prev is not None and (now - float(prev)) < 120.0:
            return True
        seen[fp] = now
        if len(seen) > 4096:
            cutoff = now - 120.0
            stale = [k for k, ts in seen.items() if float(ts) < cutoff]
            for k in stale:
                seen.pop(k, None)
            if len(seen) > 4096:
                extra = list(seen.keys())[: len(seen) - 2048]
                for k in extra:
                    seen.pop(k, None)
        return False

    def _attestation_local_head_reject_reason(self, data: Dict) -> str:
        """Empty if unknown locally or consistent; else strike for height mismatch."""
        if not isinstance(data, dict):
            return ""
        block_hash = str(data.get("target_hash") or "").strip()
        if not block_hash:
            return ""
        th_raw = data.get("target_height")
        if th_raw is None:
            return ""
        try:
            want_h = int(th_raw)
        except (TypeError, ValueError):
            return ""
        blk = self.get_block(block_hash)
        if not isinstance(blk, dict):
            return ""
        try:
            local_h = int(blk.get("height", blk.get("number", -1)))
        except (TypeError, ValueError):
            return ""
        if local_h < 0:
            return ""
        if local_h != want_h:
            return "attestation_local_height_mismatch"
        return ""

    def _attestation_target_head_refuse_reason(self, data: Dict) -> str:
        """v1.3.167: tip-height attestation must cite local tip hash.

        Soft LMD ownership — not tip proof / Long-Range / weak-subjectivity.
        """
        if not bool(getattr(self.config, "p2p_attestation_target_head_bind", True)):
            return ""
        if not isinstance(data, dict):
            return ""
        th_raw = data.get("target_height")
        if th_raw is None:
            return ""
        try:
            want_h = int(th_raw)
            tip_h = int(self.blockchain.get_height() or 0)
        except (TypeError, ValueError):
            return ""
        if tip_h <= 0 or want_h != tip_h:
            return ""
        block_hash = str(data.get("target_hash") or "").strip()
        local_tip, unreadable = self._try_local_head()
        if unreadable:
            return unreadable
        if block_hash and local_tip and block_hash.lower() != local_tip.lower():
            return "attestation_target_head_mismatch"
        return ""

    def _local_attestation_anchor(self) -> int:
        """Local tip/slot used as soft attestation ahead reference."""
        local = int(self.blockchain.get_height() or 0)
        consensus = self._consensus
        if consensus is not None:
            eng = getattr(consensus, "engine", None)
            if eng is not None:
                try:
                    local = max(local, int(getattr(eng, "current_slot", 0) or 0))
                except (TypeError, ValueError):
                    pass
        return local

    def _attestation_ahead_reject_reason(self, data: Dict) -> str:
        """Empty if within window; else strike reason for far-ahead attestation."""
        max_ahead = int(
            getattr(self.config, "p2p_max_attestation_slot_ahead", 0) or 0
        )
        if max_ahead <= 0:
            max_ahead = int(
                getattr(self.config, "p2p_max_peer_height_ahead", 100_000) or 100_000
            )
        if max_ahead <= 0:
            return ""
        ceiling = self._local_attestation_anchor() + max_ahead
        for key, reason in (
            ("slot", "attestation_slot_ahead"),
            ("target_height", "attestation_height_ahead"),
        ):
            raw = data.get(key) if isinstance(data, dict) else None
            if raw is None:
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > ceiling:
                return reason
        return ""

    async def _relay_attestation(self, attestation: Dict, exclude_peer: str = ""):
        tasks = []
        for pid, peer in list(self.peers.items()):
            if pid != exclude_peer:
                tasks.append(peer.send(MSG_ATTESTATION, attestation))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._record_broadcast_results(results, kind="attestation_relay")

    async def _handle_new_block(self, peer: PeerConnection, data: Dict):
        """Принимаем анонс нового блока от пира."""
        announce = native.validate_p2p_block_announce(data)
        if not announce:
            self._strike_peer_sync(peer, "bad_block_announce")
            return

        block_h = int(announce.get("height", 0) or 0)
        block_hash = announce.get("hash", "")
        owned_h, was_capped = self._cap_claimed_peer_height(block_h)
        # v1.3.134/135: soft ownership gate — fantasy gossip must not inflate peer tip
        # or schedule unbounded catch-up (same window as status/handshake).
        if was_capped:
            self._new_block_height_cap_total = int(
                self._new_block_height_cap_total or 0
            ) + 1
            peer.height = max(int(peer.height or 0), owned_h)
            # v1.3.159: clear fantasy head with capped height (handshake parity).
            if bool(getattr(self.config, "p2p_height_cap_clear_head", True)):
                peer.head = ""
            return

        # v1.3.153: if announce hash is already known locally, height must match
        # that header (soft ownership — not tip existence proof).
        bind_reason = self._new_block_head_height_refuse_reason(block_hash, block_h)
        if bind_reason:
            self._new_block_head_height_mismatch_total = int(
                getattr(self, "_new_block_head_height_mismatch_total", 0) or 0
            ) + 1
            self._strike_peer_sync(peer, bind_reason)
            return

        # v1.3.156: parse + announce↔body bind BEFORE tip mutate (soft ownership).
        from core.blockchain import Block
        try:
            block = Block.from_dict(data)
        except Exception as e:
            logger.warning("[P2P] Invalid block from %s: %s", peer.peer_id or peer, e)
            self._strike_peer_sync(peer, "bad_block_from_dict")
            return
        body_reason = self._new_block_announce_body_refuse_reason(
            block_hash, block_h, block
        )
        if body_reason:
            self._new_block_announce_body_refuse_total = int(
                getattr(self, "_new_block_announce_body_refuse_total", 0) or 0
            ) + 1
            self._strike_peer_sync(peer, body_reason)
            return

        # v1.3.160: contiguous (+1) announce must cite local tip as parent.
        local_h = int(self.blockchain.get_height() or 0)
        parent_reason = self._new_block_contiguous_parent_refuse_reason(block, local_h)
        if parent_reason:
            self._new_block_contiguous_parent_mismatch_total = int(
                getattr(self, "_new_block_contiguous_parent_mismatch_total", 0) or 0
            ) + 1
            self._strike_peer_sync(peer, parent_reason)
            return

        # v1.3.170: same-height sibling announce must share tip-height parent.
        same_h_reason = self._new_block_same_height_parent_refuse_reason(
            block, local_h
        )
        if same_h_reason:
            self._new_block_same_height_parent_mismatch_total = int(
                getattr(
                    self, "_new_block_same_height_parent_mismatch_total", 0
                )
                or 0
            ) + 1
            self._strike_peer_sync(peer, same_h_reason)
            return

        peer.height = max(int(peer.height or 0), block_h)
        if block_hash:
            peer.head = block_hash
        existing = self.blockchain.get_block(block.height)
        if existing:
            if existing.get("hash") == block.hash:
                return
            self._feed_fork_choice(data)
            self._feed_fork_choice(existing)
            ghost_head = self._ghost_canonical_head()
            local_head = self.head() or ""
            if ghost_head and ghost_head.lower() != local_head.lower():
                if await self._reconcile_ghost_head(ghost_head, peer_hint=peer):
                    return
            print(
                f"[P2P] Fork block #{block.height} from {peer.peer_id[:8]} — reconciling"
            )
            await self._reconcile_fork_at_peer(peer)
            return

        self._feed_fork_choice(data)
        if block.height > local_h + 1:
            self._schedule_sync(peer)
            return

        if await self._import_block_async(data):
            # v1.3.174: successful import must leave tip digest == announce hash.
            want_hash = str(
                getattr(block, "hash", "") or block_hash or ""
            ).strip()
            tip_reason = self._new_block_tip_head_refuse_reason(
                want_hash, int(getattr(block, "height", block_h) or block_h)
            )
            if tip_reason:
                self._new_block_tip_head_mismatch_total = int(
                    getattr(self, "_new_block_tip_head_mismatch_total", 0) or 0
                ) + 1
                logger.info(
                    "[P2P] new_block tip-head refuse %s peer=%s want=%s tip=%s",
                    tip_reason,
                    (peer.peer_id or "")[:12],
                    want_hash[:16],
                    (self.head() or "")[:16],
                )
                self._strike_peer_sync(peer, tip_reason)
                return
            # v1.3.66: drop mempool txs only after successful import
            for tx in block.transactions:
                self.mempool.remove(tx.hash)
            print(f"[P2P] Accepted block #{block.height} from {peer.peer_id[:8]}")
            if self.sync_engine:
                await self.refresh_consistency()
            if self._consensus and self.validator_keys:
                try:
                    # Match proposer attestation slot (block forged at slot height-1).
                    attest_slot = max(0, int(block.height) - 1)
                    self._consensus.attest(
                        self.validator_keys.get_address(),
                        block.hash,
                        slot=attest_slot,
                    )
                except Exception as exc:
                    self._attestation_local_fail += 1
                    logger.warning(
                        "[P2P] local attest failed after accept #%s: %s",
                        getattr(block, "height", "?"),
                        exc,
                    )
            await self._broadcast_block(data, exclude_peer=peer.peer_id)
        else:
            # v1.3.145: failed import feeds peer quality score (eclipse/evict).
            self._note_peer_import_fail(peer)

    async def _handle_get_blocks(self, peer: PeerConnection, data: Dict):
        """Отправляем диапазон блоков пиру."""
        rng = native.validate_p2p_get_blocks_payload(data)
        if not rng:
            self._strike_peer_sync(peer, "bad_get_blocks")
            return
        start = int(rng.get("from_height", 0))
        end = int(rng.get("to_height", start + self.config.sync_batch_size))
        # v1.3.180: do not serve ranges that start above local tip.
        refuse = self._get_blocks_future_refuse_reason(start)
        if refuse:
            self._get_blocks_future_refuse_total = int(
                getattr(self, "_get_blocks_future_refuse_total", 0) or 0
            ) + 1
            logger.info(
                "[P2P] get_blocks future refuse %s peer=%s from=%s local=%s",
                refuse,
                (peer.peer_id or "")[:12],
                start,
                self.blockchain.get_height() if self.blockchain else 0,
            )
            await peer.send(MSG_BLOCKS, [])
            return
        # v1.3.182: clamp inclusive end to local tip — no DB fetch above tip.
        end, clamp_reason = self._get_blocks_past_tip_clamp_end(start, end)
        if clamp_reason:
            self._get_blocks_past_tip_clamp_total = int(
                getattr(self, "_get_blocks_past_tip_clamp_total", 0) or 0
            ) + 1
            logger.info(
                "[P2P] get_blocks past-tip clamp %s peer=%s from=%s end=%s local=%s",
                clamp_reason,
                (peer.peer_id or "")[:12],
                start,
                end,
                self.blockchain.get_height() if self.blockchain else 0,
            )
        batch = int(getattr(self.config, "sync_batch_size", 0) or 0)
        if batch <= 0:
            batch = 64
        limit = min(end + 1, start + batch)
        bc = self.blockchain

        def _load_range() -> list:
            out = []
            for h in range(start, limit):
                blk = bc.get_block(h)
                if blk:
                    out.append(blk)
            return out

        blocks = await asyncio.to_thread(_load_range)
        await peer.send(MSG_BLOCKS, blocks)

    def _get_blocks_future_refuse_reason(self, from_height: int) -> str:
        """v1.3.180: GET_BLOCKS from_height must not exceed local tip.

        Soft bandwidth/DoS honesty — fantasy future ranges get empty reply.
        Not tip proof / Long-Range.
        """
        if not bool(getattr(self.config, "p2p_get_blocks_future_refuse", True)):
            return ""
        try:
            start = int(from_height)
            local_h = int(self.blockchain.get_height() or 0)
        except (TypeError, ValueError):
            return ""
        if start < 0:
            return ""
        if start > local_h:
            return "get_blocks_future_height"
        return ""

    def _get_block_future_refuse_reason(self, height: int) -> str:
        """v1.3.181: GET_BLOCK height must not exceed local tip.

        Soft bandwidth/DoS honesty — fantasy future single fetches get null.
        Not tip proof / Long-Range.
        """
        if not bool(getattr(self.config, "p2p_get_block_future_refuse", True)):
            return ""
        try:
            h = int(height)
            local_h = int(self.blockchain.get_height() or 0)
        except (TypeError, ValueError):
            return ""
        if h < 0:
            return ""
        if h > local_h:
            return "get_block_future_height"
        return ""

    def _get_blocks_past_tip_clamp_end(self, from_height: int, to_height: int):
        """v1.3.182: clamp GET_BLOCKS inclusive end to local tip.

        Soft bandwidth/DoS honesty — no DB lookups for heights above tip
        inside an otherwise valid from_height window. Not tip proof.
        Returns (inclusive_end, reason_or_empty).
        """
        try:
            start = int(from_height)
            end = int(to_height)
            local_h = int(self.blockchain.get_height() or 0)
        except (TypeError, ValueError):
            try:
                return int(to_height), ""
            except (TypeError, ValueError):
                return 0, ""
        if not bool(getattr(self.config, "p2p_get_blocks_past_tip_clamp", True)):
            return end, ""
        if end > local_h and start <= local_h:
            return local_h, "get_blocks_past_tip_clamp"
        return end, ""

    def _record_tx_propagation(
        self,
        tx_hash: str,
        stage: str,
        peer_id: str = "",
        block_height: int = 0,
        detail: Optional[Dict] = None,
    ) -> None:
        db = getattr(self.blockchain, "db", None)
        if not db or not hasattr(db, "record_tx_propagation_event"):
            return
        try:
            db.record_tx_propagation_event(
                tx_hash,
                stage,
                node_id=getattr(self.config, "node_id", ""),
                peer_id=peer_id,
                block_height=block_height,
                detail=detail or {},
            )
        except Exception as exc:
            self._propagation_log_fail += 1
            logger.warning(
                "[P2P] record_tx_propagation_event failed stage=%s tx=%s: %s",
                stage,
                (tx_hash or "")[:16],
                exc,
            )

    def _build_mempool_tx_from_wire(self, data: Dict):
        """Build a mempool entry from wire-format tx; None if invalid.

        v1.3.143: after native shape, skip known hashes before validate_transaction
        (cheap refuse). Soft DoS honesty only — not anti-Sybil / tip proof.
        v1.3.177: also refuse fee < mempool.min_fee before validate_transaction.
        v1.3.201: also refuse fee > max_fee before validate_transaction.
        v1.3.179: also refuse gas > evm_gas_limit before validate_transaction.
        v1.3.183: also refuse oversized calldata before validate_transaction.
        v1.3.184: also refuse value < 0 before validate_transaction.
        v1.3.202: also refuse value > max_value before validate_transaction.
        v1.3.185: also refuse nonce < 0 before validate_transaction.
        v1.3.200: also refuse oversized nonce before validate_transaction.
        v1.3.186: also refuse fee < 0 before validate_transaction.
        v1.3.187: also refuse gas < 0 before validate_transaction.
        v1.3.203: also refuse unparseable gas before validate_transaction.
        v1.3.204: also refuse unparseable value before validate_transaction.
        v1.3.205: also refuse unparseable nonce before validate_transaction.
        v1.3.188: also refuse empty from address before validate_transaction.
        v1.3.198: also refuse oversized from address before validate_transaction.
        v1.3.195: also refuse empty to address before validate_transaction.
        v1.3.199: also refuse oversized to address before validate_transaction.
        v1.3.196: also refuse empty hash before validate_transaction.
        v1.3.197: also refuse oversized hash before validate_transaction.
        v1.3.189: also refuse empty signature before validate_transaction.
        v1.3.190: also refuse empty public_key before validate_transaction.
        v1.3.191: also refuse oversized signature before validate_transaction.
        v1.3.192: also refuse oversized public_key before validate_transaction.
        v1.3.193: also refuse NaN/Inf value before validate_transaction.
        v1.3.194: also refuse NaN/Inf fee before validate_transaction.
        """
        self._last_tx_wire_reject = ""
        if not native.validate_p2p_wire_tx(data):
            self._last_tx_wire_reject = "bad_wire_tx"
            return None
        from core.blockchain import Transaction
        from blockchain.mempool import MempoolTransaction

        from_addr = data.get("from_addr", data.get("from", ""))
        to_addr = data.get("to_addr", data.get("to", ""))
        # v1.3.204: junk value must refuse, not raise into the ingest path.
        # parse_p2p_wire_abs: bool/hex are unparseable (float(True)==1.0 would mint 1 ABS).
        # IEEE NaN/Inf stay on the v1.3.193 non-finite path (reason_code preserved).
        raw_value = data.get("value", data.get("amount", 0))
        if isinstance(raw_value, float) and not math.isfinite(raw_value):
            if bool(getattr(self.config, "p2p_mempool_nonfinite_value_refuse", True)):
                self._last_tx_wire_reject = "value_non_finite"
                self._mempool_nonfinite_value_refuse_total = int(
                    getattr(self, "_mempool_nonfinite_value_refuse_total", 0) or 0
                ) + 1
                return None
        try:
            value = parse_p2p_wire_abs(raw_value, field="value")
        except (TypeError, ValueError):
            if bool(getattr(self.config, "p2p_mempool_unparseable_value_refuse", True)):
                self._last_tx_wire_reject = "value_unparseable"
                self._mempool_value_unparseable_refuse_total = int(
                    getattr(self, "_mempool_value_unparseable_refuse_total", 0) or 0
                ) + 1
                return None
            value = 0.0
        # v1.3.205: junk nonce must refuse, not raise into the ingest path.
        try:
            nonce = int(data.get("nonce", 0))
        except (TypeError, ValueError, OverflowError):
            if bool(getattr(self.config, "p2p_mempool_unparseable_nonce_refuse", True)):
                self._last_tx_wire_reject = "nonce_unparseable"
                self._mempool_nonce_unparseable_refuse_total = int(
                    getattr(self, "_mempool_nonce_unparseable_refuse_total", 0) or 0
                ) + 1
                return None
            nonce = 0
        # v1.3.203: Inf/junk gas must refuse, not raise into the ingest path.
        try:
            gas = int(data.get("gas", 0) or 0) or 21_000
        except (TypeError, ValueError, OverflowError):
            if bool(getattr(self.config, "p2p_mempool_unparseable_gas_refuse", True)):
                self._last_tx_wire_reject = "gas_unparseable"
                self._mempool_gas_unparseable_refuse_total = int(
                    getattr(self, "_mempool_gas_unparseable_refuse_total", 0) or 0
                ) + 1
                return None
            gas = 21_000
        signature = data.get("signature", "")
        public_key = data.get("public_key", "")
        calldata = data.get("data", data.get("input", ""))
        tx_hash = str(data.get("hash", data.get("tx_hash", "")) or "").strip()

        # v1.3.188: cheap empty-from refuse before validate_transaction (ECDSA/state).
        # Soft DoS honesty — not address checksum / anti-Sybil.
        if bool(getattr(self.config, "p2p_mempool_empty_from_refuse", True)):
            if not str(from_addr or "").strip():
                self._last_tx_wire_reject = "from_empty"
                self._mempool_empty_from_refuse_total = int(
                    getattr(self, "_mempool_empty_from_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.198: cheap oversized-from refuse before validate_transaction.
        # Soft DoS honesty — aligns MAX_P2P_ADDR_LEN; not checksum / anti-Sybil.
        if bool(getattr(self.config, "p2p_mempool_max_from_refuse", True)):
            try:
                max_addr = int(
                    getattr(self.config, "p2p_mempool_max_addr_chars", 128) or 128
                )
            except (TypeError, ValueError):
                max_addr = 128
            if max_addr > 0 and len(str(from_addr or "").strip()) > max_addr:
                self._last_tx_wire_reject = "from_too_large"
                self._mempool_from_size_refuse_total = int(
                    getattr(self, "_mempool_from_size_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.195: cheap empty-to refuse before validate_transaction (state).
        # Soft DoS honesty — mirrors from_empty; not contract-create / checksum.
        if bool(getattr(self.config, "p2p_mempool_empty_to_refuse", True)):
            if not str(to_addr or "").strip():
                self._last_tx_wire_reject = "to_empty"
                self._mempool_empty_to_refuse_total = int(
                    getattr(self, "_mempool_empty_to_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.199: cheap oversized-to refuse before validate_transaction.
        # Soft DoS honesty — mirrors from_too_large; aligns MAX_P2P_ADDR_LEN.
        if bool(getattr(self.config, "p2p_mempool_max_to_refuse", True)):
            try:
                max_addr = int(
                    getattr(self.config, "p2p_mempool_max_addr_chars", 128) or 128
                )
            except (TypeError, ValueError):
                max_addr = 128
            if max_addr > 0 and len(str(to_addr or "").strip()) > max_addr:
                self._last_tx_wire_reject = "to_too_large"
                self._mempool_to_size_refuse_total = int(
                    getattr(self, "_mempool_to_size_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.189: cheap empty-signature refuse before validate_transaction (ECDSA).
        # Soft DoS honesty — not full sig verify / tip proof.
        if bool(getattr(self.config, "p2p_mempool_empty_sig_refuse", True)):
            if not str(signature or "").strip():
                self._last_tx_wire_reject = "signature_empty"
                self._mempool_empty_sig_refuse_total = int(
                    getattr(self, "_mempool_empty_sig_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.191: cheap oversized-signature refuse before validate_transaction.
        # Soft DoS honesty — not full ECDSA; complements signature_empty.
        if bool(getattr(self.config, "p2p_mempool_max_sig_refuse", True)):
            try:
                max_sig = int(
                    getattr(self.config, "p2p_mempool_max_sig_bytes", 2048) or 2048
                )
            except (TypeError, ValueError):
                max_sig = 2048
            if max_sig > 0 and self._wire_calldata_byte_len(signature) > max_sig:
                self._last_tx_wire_reject = "signature_too_large"
                self._mempool_sig_size_refuse_total = int(
                    getattr(self, "_mempool_sig_size_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.190: cheap empty-pubkey refuse before validate_transaction (ECDSA).
        # Soft DoS honesty — not key format / tip proof.
        if bool(getattr(self.config, "p2p_mempool_empty_pubkey_refuse", True)):
            if not str(public_key or "").strip():
                self._last_tx_wire_reject = "pubkey_empty"
                self._mempool_empty_pubkey_refuse_total = int(
                    getattr(self, "_mempool_empty_pubkey_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.192: cheap oversized-pubkey refuse before validate_transaction.
        # Soft DoS honesty — not key-format validation; complements pubkey_empty.
        if bool(getattr(self.config, "p2p_mempool_max_pubkey_refuse", True)):
            try:
                max_pk = int(
                    getattr(self.config, "p2p_mempool_max_pubkey_bytes", 2048) or 2048
                )
            except (TypeError, ValueError):
                max_pk = 2048
            if max_pk > 0 and self._wire_calldata_byte_len(public_key) > max_pk:
                self._last_tx_wire_reject = "pubkey_too_large"
                self._mempool_pubkey_size_refuse_total = int(
                    getattr(self, "_mempool_pubkey_size_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.196: cheap empty-hash refuse before validate_transaction.
        # Soft DoS honesty — empty hash skips duplicate_tx cheap path; not hash binding.
        if bool(getattr(self.config, "p2p_mempool_empty_hash_refuse", True)):
            if not tx_hash:
                self._last_tx_wire_reject = "hash_empty"
                self._mempool_empty_hash_refuse_total = int(
                    getattr(self, "_mempool_empty_hash_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.197: cheap oversized-hash refuse before validate_transaction.
        # Soft DoS honesty — aligns MAX_P2P_HASH_LEN; not hash↔body binding.
        if bool(getattr(self.config, "p2p_mempool_max_hash_refuse", True)):
            try:
                max_hash = int(
                    getattr(self.config, "p2p_mempool_max_hash_chars", 128) or 128
                )
            except (TypeError, ValueError):
                max_hash = 128
            if max_hash > 0 and len(tx_hash) > max_hash:
                self._last_tx_wire_reject = "hash_too_large"
                self._mempool_hash_size_refuse_total = int(
                    getattr(self, "_mempool_hash_size_refuse_total", 0) or 0
                ) + 1
                return None

        # Cheap duplicate refuse before DB/nonce/sig path.
        if tx_hash and self.mempool is not None:
            try:
                if self.mempool.has_transaction(tx_hash):
                    self._last_tx_wire_reject = "duplicate_tx"
                    self._mempool_dup_refuse_total = int(
                        getattr(self, "_mempool_dup_refuse_total", 0) or 0
                    ) + 1
                    return None
            except Exception as exc:
                logger.warning("mempool has_transaction check failed: %s", exc)
                self._last_tx_wire_reject = "mempool_dup_check_failed"
                return None

        # v1.3.177: cheap min-fee refuse before validate_transaction (ECDSA/state).
        # Soft DoS honesty — not Rust gas priority queue / EIP-1559 lanes.
        raw_fee = data.get("fee", None)
        if isinstance(raw_fee, float) and not math.isfinite(raw_fee):
            if bool(getattr(self.config, "p2p_mempool_nonfinite_fee_refuse", True)):
                self._last_tx_wire_reject = "fee_non_finite"
                self._mempool_nonfinite_fee_refuse_total = int(
                    getattr(self, "_mempool_nonfinite_fee_refuse_total", 0) or 0
                ) + 1
                return None
        try:
            if raw_fee is None:
                fee = parse_p2p_wire_abs(
                    gas * float(getattr(self.config, "gas_price_wei", 0.001) or 0.001),
                    field="fee",
                )
            else:
                fee = parse_p2p_wire_abs(raw_fee, field="fee")
        except (TypeError, ValueError):
            self._last_tx_wire_reject = "fee_unparseable"
            self._mempool_fee_unparseable_refuse_total = int(
                getattr(self, "_mempool_fee_unparseable_refuse_total", 0) or 0
            ) + 1
            return None
        if bool(getattr(self.config, "p2p_mempool_min_fee_refuse", True)):
            min_fee = 0.0
            if self.mempool is not None:
                try:
                    min_fee = float(getattr(self.mempool, "min_fee", 0) or 0)
                except (TypeError, ValueError):
                    min_fee = 0.0
            if min_fee > 0 and fee < min_fee:
                self._last_tx_wire_reject = "fee_too_low"
                self._mempool_fee_refuse_total = int(
                    getattr(self, "_mempool_fee_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.179: cheap gas ceiling refuse before validate_transaction.
        # Soft DoS honesty — not Rust gas priority queue / EIP-1559 lanes.
        if bool(getattr(self.config, "p2p_mempool_max_gas_refuse", True)):
            try:
                max_gas = int(
                    getattr(self.config, "evm_gas_limit", 8_000_000) or 8_000_000
                )
            except (TypeError, ValueError):
                max_gas = 8_000_000
            if max_gas > 0 and gas > max_gas:
                self._last_tx_wire_reject = "gas_too_high"
                self._mempool_gas_refuse_total = int(
                    getattr(self, "_mempool_gas_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.183: cheap calldata size refuse before validate_transaction.
        # Soft DoS honesty — not full tx-size RLP budget / Rust mempool.
        if bool(getattr(self.config, "p2p_mempool_max_calldata_refuse", True)):
            try:
                max_cd = int(
                    getattr(self.config, "p2p_mempool_max_calldata_bytes", 131072)
                    or 131072
                )
            except (TypeError, ValueError):
                max_cd = 131072
            if max_cd > 0 and self._wire_calldata_byte_len(calldata) > max_cd:
                self._last_tx_wire_reject = "calldata_too_large"
                self._mempool_calldata_refuse_total = int(
                    getattr(self, "_mempool_calldata_refuse_total", 0) or 0
                ) + 1
                return None

        # v1.3.184: cheap negative-value refuse before validate_transaction.
        # Soft DoS honesty — not amount-cap economics / full tokenomics port.
        if bool(getattr(self.config, "p2p_mempool_negative_value_refuse", True)):
            try:
                if float(value) < 0.0:
                    self._last_tx_wire_reject = "value_negative"
                    self._mempool_value_refuse_total = int(
                        getattr(self, "_mempool_value_refuse_total", 0) or 0
                    ) + 1
                    return None
            except (TypeError, ValueError):
                pass

        # v1.3.193: cheap non-finite value refuse before validate_transaction.
        # Soft DoS honesty — NaN/Inf slip past value_negative; not amount-cap economics.
        if bool(getattr(self.config, "p2p_mempool_nonfinite_value_refuse", True)):
            try:
                if not math.isfinite(float(value)):
                    self._last_tx_wire_reject = "value_non_finite"
                    self._mempool_nonfinite_value_refuse_total = int(
                        getattr(self, "_mempool_nonfinite_value_refuse_total", 0) or 0
                    ) + 1
                    return None
            except (TypeError, ValueError):
                pass

        # v1.3.202: cheap max-value refuse before validate_transaction.
        # Soft DoS honesty — fantasy amounts fail before DB; not full tokenomics/economics.
        if bool(getattr(self.config, "p2p_mempool_max_value_refuse", True)):
            try:
                max_value = float(
                    getattr(self.config, "p2p_mempool_max_value", 221_000_000.0)
                    or 221_000_000.0
                )
            except (TypeError, ValueError):
                max_value = 221_000_000.0
            try:
                if max_value > 0 and float(value) > max_value:
                    self._last_tx_wire_reject = "value_too_high"
                    self._mempool_value_high_refuse_total = int(
                        getattr(self, "_mempool_value_high_refuse_total", 0) or 0
                    ) + 1
                    return None
            except (TypeError, ValueError):
                pass

        # v1.3.185: cheap negative-nonce refuse before validate_transaction.
        # Soft DoS honesty — not account-nonce window / full mempool scheduler.
        if bool(getattr(self.config, "p2p_mempool_negative_nonce_refuse", True)):
            try:
                if int(nonce) < 0:
                    self._last_tx_wire_reject = "nonce_negative"
                    self._mempool_nonce_refuse_total = int(
                        getattr(self, "_mempool_nonce_refuse_total", 0) or 0
                    ) + 1
                    return None
            except (TypeError, ValueError):
                pass

        # v1.3.200: cheap max-nonce refuse before validate_transaction.
        # Soft DoS honesty — fantasy nonces skip cheap before DB; not nonce-window.
        if bool(getattr(self.config, "p2p_mempool_max_nonce_refuse", True)):
            try:
                max_nonce = int(
                    getattr(self.config, "p2p_mempool_max_nonce", 1_000_000_000_000)
                    or 1_000_000_000_000
                )
            except (TypeError, ValueError):
                max_nonce = 1_000_000_000_000
            try:
                if max_nonce > 0 and int(nonce) > max_nonce:
                    self._last_tx_wire_reject = "nonce_too_high"
                    self._mempool_nonce_high_refuse_total = int(
                        getattr(self, "_mempool_nonce_high_refuse_total", 0) or 0
                    ) + 1
                    return None
            except (TypeError, ValueError):
                pass

        # v1.3.186: cheap negative-fee refuse before validate_transaction.
        # Soft DoS honesty — complements fee_too_low when min_fee==0; not Rust fee PQ.
        if bool(getattr(self.config, "p2p_mempool_negative_fee_refuse", True)):
            try:
                if float(fee) < 0.0:
                    self._last_tx_wire_reject = "fee_negative"
                    self._mempool_fee_negative_refuse_total = int(
                        getattr(self, "_mempool_fee_negative_refuse_total", 0) or 0
                    ) + 1
                    return None
            except (TypeError, ValueError):
                pass

        # v1.3.194: cheap non-finite fee refuse before validate_transaction.
        # Soft DoS honesty — NaN/Inf slip past fee_negative; not Rust fee PQ.
        if bool(getattr(self.config, "p2p_mempool_nonfinite_fee_refuse", True)):
            try:
                if not math.isfinite(float(fee)):
                    self._last_tx_wire_reject = "fee_non_finite"
                    self._mempool_nonfinite_fee_refuse_total = int(
                        getattr(self, "_mempool_nonfinite_fee_refuse_total", 0) or 0
                    ) + 1
                    return None
            except (TypeError, ValueError):
                pass

        # v1.3.201: cheap max-fee refuse before validate_transaction.
        # Soft DoS honesty — complements fee_too_low; not fee-market / Rust fee PQ.
        if bool(getattr(self.config, "p2p_mempool_max_fee_refuse", True)):
            try:
                max_fee = float(
                    getattr(self.config, "p2p_mempool_max_fee", 1_000_000_000.0)
                    or 1_000_000_000.0
                )
            except (TypeError, ValueError):
                max_fee = 1_000_000_000.0
            try:
                if max_fee > 0 and float(fee) > max_fee:
                    self._last_tx_wire_reject = "fee_too_high"
                    self._mempool_fee_high_refuse_total = int(
                        getattr(self, "_mempool_fee_high_refuse_total", 0) or 0
                    ) + 1
                    return None
            except (TypeError, ValueError):
                pass

        # v1.3.187: cheap negative-gas refuse before validate_transaction.
        # Soft DoS honesty — complements gas_too_high; not Rust gas PQ.
        # Note: `gas = int(...) or 21000` keeps negatives (truthy), only 0 defaults.
        if bool(getattr(self.config, "p2p_mempool_negative_gas_refuse", True)):
            try:
                if int(gas) < 0:
                    self._last_tx_wire_reject = "gas_negative"
                    self._mempool_gas_negative_refuse_total = int(
                        getattr(self, "_mempool_gas_negative_refuse_total", 0) or 0
                    ) + 1
                    return None
            except (TypeError, ValueError):
                pass

        tx = Transaction(
            from_addr=from_addr,
            to_addr=to_addr,
            value=value,
            nonce=nonce,
            gas=gas,
            data=calldata,
            signature=signature,
            public_key=public_key,
            tx_hash=tx_hash,
        )
        validation = self.blockchain.validate_transaction(tx)
        if not validation["valid"]:
            self._last_tx_wire_reject = str(validation.get("error") or "invalid")
            return None

        mp_tx = MempoolTransaction(
            tx_hash=tx.hash,
            from_addr=from_addr,
            to_addr=to_addr,
            amount=value,
            fee=fee,
            nonce=nonce,
            signature=signature,
            public_key=public_key,
            data=calldata,
            gas=gas,
        )
        return mp_tx, tx.hash

    @staticmethod
    def _wire_calldata_byte_len(calldata) -> int:
        """Approximate on-wire calldata size in bytes (hex or raw string)."""
        if calldata is None:
            return 0
        if isinstance(calldata, (bytes, bytearray)):
            return len(calldata)
        s = str(calldata)
        if s.startswith(("0x", "0X")):
            hexpart = s[2:]
            return (len(hexpart) + 1) // 2
        return len(s.encode("utf-8", errors="replace"))

    async def _ingest_peer_tx(
        self,
        data: Dict,
        source: str = "p2p_gossip",
        peer_id: str = "",
        peer: Optional[PeerConnection] = None,
        *,
        strike_on_reject: bool = False,
    ) -> bool:
        """Validate and add a wire-format tx to mempool; record propagation stages."""
        built = self._build_mempool_tx_from_wire(data)
        if not built:
            err = self._last_tx_wire_reject or "invalid"
            self._peer_tx_reject = int(self._peer_tx_reject or 0) + 1
            logger.warning(
                "[P2P] Tx rejected (%s peer=%s): %s",
                source,
                (peer_id or "?")[:12],
                err,
            )
            if strike_on_reject and peer is not None:
                self._strike_peer_sync(peer, "bad_peer_tx")
            return False
        mp_tx, tx_hash = built
        # Already passed validate_transaction (sig + state); skip duplicate work in add().
        if not self.mempool.add(
            mp_tx, signature_preverified=True, chain_prevalidated=True
        ):
            self._peer_tx_reject = int(self._peer_tx_reject or 0) + 1
            logger.warning(
                "[P2P] Tx mempool drop (%s peer=%s hash=%s)",
                source,
                (peer_id or "?")[:12],
                str(tx_hash)[:12],
            )
            return False

        stage_recv = "mempool_sync" if source == "mempool_sync" else "p2p_received"
        self._record_tx_propagation(
            tx_hash,
            stage_recv,
            peer_id=peer_id,
            detail={"source": source},
        )
        self._record_tx_propagation(
            tx_hash,
            "mempool_remote",
            peer_id=peer_id,
            detail={"mempool_size": self.mempool.get_size()},
        )
        logger.debug(f"[P2P] Accepted tx {tx_hash[:12]}… ({source})")
        return True

    async def _handle_new_tx(self, peer: PeerConnection, data: Dict):
        """Принимаем транзакцию из gossip."""
        peer_id = getattr(peer, "peer_id", "") if peer else ""
        await self._ingest_peer_tx(
            data,
            source="p2p_gossip",
            peer_id=peer_id,
            peer=peer,
            strike_on_reject=True,
        )

    async def _handle_get_mempool(self, peer: PeerConnection):
        from blockchain.mempool_wire import mempool_tx_to_wire

        # v1.3.178: do not serialize a mempool dump for far tip peers.
        refuse = self._get_mempool_tip_align_refuse_reason(peer)
        if refuse:
            self._get_mempool_tip_misaligned_total = int(
                getattr(self, "_get_mempool_tip_misaligned_total", 0) or 0
            ) + 1
            logger.info(
                "[P2P] get_mempool tip-align refuse %s peer=%s peer_h=%s local_h=%s",
                refuse,
                (peer.peer_id or "")[:12],
                getattr(peer, "height", 0),
                self.blockchain.get_height() if self.blockchain else 0,
            )
            await peer.send(MSG_MEMPOOL, {"transactions": [], "count": 0})
            return
        pending = self.mempool.get(limit=200)
        wire = [mempool_tx_to_wire(t) for t in pending]
        await peer.send(MSG_MEMPOOL, {"transactions": wire, "count": len(wire)})

    def _get_mempool_tip_align_refuse_reason(self, peer: PeerConnection) -> str:
        """v1.3.178: serve mempool dump only when peer tip is near local tip.

        Soft bandwidth/DoS honesty — same ±2 window as outbound mempool pull.
        Not tip proof / Long-Range / Rust fee scheduler.
        """
        if not bool(getattr(self.config, "p2p_mempool_serve_tip_align", True)):
            return ""
        try:
            local_h = int(self.blockchain.get_height() or 0)
            peer_h = int(getattr(peer, "height", 0) or 0)
            max_delta = int(
                getattr(self.config, "p2p_mempool_serve_max_height_delta", 2) or 2
            )
        except (TypeError, ValueError):
            return ""
        if max_delta < 0:
            max_delta = 0
        if abs(peer_h - local_h) > max_delta:
            return "get_mempool_tip_misaligned"
        return ""

    async def _handle_mempool_batch(self, peer: PeerConnection, data: Dict):
        if native.validate_p2p_mempool_batch(data) is None:
            self._strike_peer_sync(peer, "bad_mempool_batch")
            return
        txs = data.get("transactions", [])
        peer_id = getattr(peer, "peer_id", "") if peer else ""
        mp_txs = []
        wire_rejects = 0
        for tx_data in txs:
            built = self._build_mempool_tx_from_wire(tx_data)
            if built:
                mp_txs.append(built[0])
            else:
                wire_rejects += 1
        if wire_rejects:
            self._peer_tx_reject = int(self._peer_tx_reject or 0) + wire_rejects
            logger.warning(
                "[P2P] Mempool batch rejects peer=%s count=%s",
                (peer_id or "?")[:12],
                wire_rejects,
            )
        if not mp_txs:
            return
        added, batch_rejected, accepted_hashes = self.mempool.add_batch(
            mp_txs, chain_prevalidated=True
        )
        if batch_rejected:
            self._peer_tx_reject = int(self._peer_tx_reject or 0) + int(batch_rejected)
        stage_recv = "mempool_sync"
        for tx_hash in accepted_hashes:
            self._record_tx_propagation(
                tx_hash,
                stage_recv,
                peer_id=peer_id,
                detail={"source": "mempool_sync"},
            )
            self._record_tx_propagation(
                tx_hash,
                "mempool_remote",
                peer_id=peer_id,
                detail={"mempool_size": self.mempool.get_size()},
            )
        if added:
            print(f"[P2P] Mempool sync from {peer_id[:8]}: +{added} tx(s)")

    async def _sync_mempool_with_peer(self, peer: PeerConnection, timeout: float = 12):
        """Pull peer mempool when chain tips are aligned (real pending tx relay)."""
        if abs(peer.height - self.blockchain.get_height()) > 2:
            return
        msg = await self._wait_peer_response(
            peer,
            (MSG_MEMPOOL,),
            timeout=timeout,
            presend=lambda: peer.send(MSG_GET_MEMPOOL, {}),
            request_ctx={"kind": "mempool"},
        )
        if msg and msg.get("type") == MSG_MEMPOOL:
            await self._handle_mempool_batch(peer, msg.get("data") or {})

    # ── Синхронизация ────────────────────────────────────────────────────────

    def _peer_lock(self, peer_id: str) -> asyncio.Lock:
        if peer_id not in self._peer_sync_locks:
            self._peer_sync_locks[peer_id] = asyncio.Lock()
        return self._peer_sync_locks[peer_id]

    def _global_catch_up_lock(self) -> asyncio.Lock:
        """Serialize PathA across peers so a failed duplicate cannot reorg a live import."""
        if self._catch_up_apply_lock is None:
            self._catch_up_apply_lock = asyncio.Lock()
        return self._catch_up_apply_lock

    def _local_known_head_height_mismatch(
        self, block_hash: str, block_h: int
    ) -> bool:
        """True when local header for hash disagrees with claimed height."""
        head = str(block_hash or "").strip()
        if not head:
            return False
        blk = None
        try:
            blk = self.get_block(head)
        except Exception as exc:
            logger.warning(
                "[P2P] get_block failed during head-height bind; treating as mismatch: %s",
                exc,
            )
            return True
        if not isinstance(blk, dict):
            return False
        try:
            local_h = int(blk.get("height", blk.get("number", -1)) or -1)
        except (TypeError, ValueError):
            local_h = -1
        try:
            claimed = int(block_h)
        except (TypeError, ValueError):
            claimed = -1
        return local_h >= 0 and claimed >= 0 and local_h != claimed

    def _new_block_head_height_refuse_reason(
        self, block_hash: str, block_h: int
    ) -> str:
        """v1.3.153: known announce hash ⇒ claimed height must match local header.

        Soft ownership only — not tip existence proof / merkle tip bind.
        """
        if not bool(getattr(self.config, "p2p_new_block_head_height_bind", True)):
            return ""
        if self._local_known_head_height_mismatch(block_hash, block_h):
            return "new_block_head_height_mismatch"
        return ""

    def _new_block_announce_body_refuse_reason(
        self, announce_hash: str, announce_h: int, block: Any
    ) -> str:
        """v1.3.156: announce hash/height must match parsed Block body.

        Soft ownership — not tip proof / Long-Range. Tip mutate is deferred until
        after this check succeeds.
        """
        if not bool(getattr(self.config, "p2p_new_block_announce_body_bind", True)):
            return ""
        claimed_hash = str(announce_hash or "").strip()
        body_hash = str(getattr(block, "hash", "") or "").strip()
        if claimed_hash and body_hash and claimed_hash.lower() != body_hash.lower():
            return "new_block_announce_hash_mismatch"
        try:
            body_h = int(getattr(block, "height", -1) or -1)
        except (TypeError, ValueError):
            body_h = -1
        try:
            claimed_h = int(announce_h)
        except (TypeError, ValueError):
            claimed_h = -1
        if body_h >= 0 and claimed_h >= 0 and body_h != claimed_h:
            return "new_block_announce_height_mismatch"
        return ""

    def _new_block_contiguous_parent_refuse_reason(
        self, block: Any, local_h: int
    ) -> str:
        """v1.3.160: when announce is exactly local+1, parent_hash must match tip.

        Soft contiguous extension — not tip proof / Long-Range.
        """
        if not bool(
            getattr(self.config, "p2p_new_block_contiguous_parent_bind", True)
        ):
            return ""
        try:
            body_h = int(getattr(block, "height", -1) or -1)
            tip_h = int(local_h)
        except (TypeError, ValueError):
            return ""
        if body_h < 0 or tip_h < 0 or body_h != tip_h + 1:
            return ""
        parent = str(getattr(block, "parent_hash", "") or "").strip()
        local_tip, unreadable = self._try_local_head()
        if unreadable:
            return unreadable
        if parent and local_tip and parent.lower() != local_tip.lower():
            return "new_block_contiguous_parent_mismatch"
        return ""

    def _new_block_same_height_parent_refuse_reason(
        self, block: Any, local_h: int
    ) -> str:
        """v1.3.170: when announce is same height as tip, parent must match tip parent.

        Soft tip-sibling ownership — not tip proof / Long-Range.
        """
        if not bool(
            getattr(self.config, "p2p_new_block_same_height_parent_bind", True)
        ):
            return ""
        try:
            body_h = int(getattr(block, "height", -1) or -1)
            tip_h = int(local_h)
        except (TypeError, ValueError):
            return ""
        if body_h < 0 or tip_h < 0 or body_h != tip_h:
            return ""
        block_hash = str(getattr(block, "hash", "") or "").strip()
        local_tip, unreadable = self._try_local_head()
        if unreadable:
            return unreadable
        if (
            block_hash
            and local_tip
            and block_hash.lower() == local_tip.lower()
        ):
            return ""
        parent = str(getattr(block, "parent_hash", "") or "").strip()
        local_parent, unreadable = self._try_expected_parent(tip_h)
        if unreadable:
            return unreadable
        if (
            parent
            and local_parent
            and local_parent != ("0" * 64)
            and parent.lower() != local_parent.lower()
        ):
            return "new_block_same_height_parent_mismatch"
        return ""

    def _new_block_tip_head_refuse_reason(
        self, target_hash: str, announced_height: int
    ) -> str:
        """v1.3.174: after new_block import, tip must match announce hash.

        Soft tip digest ownership at gossip accept — not tip proof / Long-Range.
        Only binds when tip height == announced height (exact completion).
        Empty local tip soft-skips.
        """
        if not bool(getattr(self.config, "p2p_new_block_tip_head_bind", True)):
            return ""
        want = str(target_hash or "").strip()
        if not want:
            return ""
        try:
            tip_h = int(self.blockchain.get_height() or 0)
            body_h = int(announced_height or -1)
        except (TypeError, ValueError):
            return ""
        if tip_h <= 0 or body_h < 0 or tip_h != body_h:
            return ""
        local_tip, unreadable = self._try_local_head()
        if unreadable:
            return unreadable
        if local_tip and local_tip.lower() != want.lower():
            return "new_block_tip_head_mismatch"
        return ""

    def _status_head_height_refuse_reason(
        self,
        block_hash: str,
        block_h: int,
        reason: str = "status_head_height_mismatch",
    ) -> str:
        """v1.3.155: known status/handshake head ⇒ claimed height must match.

        Soft ownership only — not tip existence proof / Long-Range.
        """
        if not bool(getattr(self.config, "p2p_status_head_height_bind", True)):
            return ""
        if self._local_known_head_height_mismatch(block_hash, block_h):
            return str(reason or "status_head_height_mismatch")
        return ""

    def _handshake_head_without_height_refuse_reason(
        self, hs_head: str, owned_h: int, local_h: int
    ) -> str:
        """v1.3.166: head without an explicit height refused when local tip > 0.

        Height 0 is a valid genesis tip — followers may still be at #0 while the
        leader has advanced. Only missing/negative height + head is refused.
        Soft ownership parity with STATUS — not tip proof / Long-Range.
        """
        if not bool(
            getattr(self.config, "p2p_handshake_head_requires_height", True)
        ):
            return ""
        head = str(hs_head or "").strip()
        if not head:
            return ""
        try:
            height = int(owned_h)
            tip = int(local_h)
        except (TypeError, ValueError):
            return ""
        # Negative sentinel = height omitted from handshake payload.
        if height < 0 and tip > 0:
            return "handshake_head_without_height"
        return ""

    def _catch_up_ahead_refuse_reason(self, peer: PeerConnection) -> str:
        """v1.3.139: refuse height-only catch-up without a concrete peer.head.

        v1.3.146: if peer.head is already known locally, claimed height must match
        that header (soft ownership — not tip existence proof).
        """
        if not bool(getattr(self.config, "p2p_catch_up_require_head", True)):
            return ""
        try:
            our_h = int(self.blockchain.get_height() or 0)
            peer_h = int(getattr(peer, "height", 0) or 0)
        except (TypeError, ValueError):
            return ""
        head = str(getattr(peer, "head", "") or "").strip()
        blk = None
        if head:
            try:
                blk = self.get_block(head)
            except Exception as exc:
                logger.warning(
                    "[P2P] get_block failed during catch-up ahead bind: %s", exc
                )
                blk = None
        policy = getattr(self, "catch_up", None) or getattr(self, "catch_up_policy", None)
        if policy is not None:
            ahead = getattr(policy, "ahead_refuse_reason", None)
            if ahead is not None:
                return ahead(
                    local_height=our_h,
                    peer_height=peer_h,
                    peer_head=head,
                    local_block_for_head=blk,
                    require_head=True,
                )
        if peer_h <= our_h:
            return ""
        if not head:
            return "catch_up_no_head"
        if isinstance(blk, dict):
            try:
                local_h = int(blk.get("height", blk.get("number", -1)) or -1)
            except (TypeError, ValueError):
                local_h = -1
            if local_h >= 0 and local_h != peer_h:
                return "catch_up_head_height_mismatch"
        return ""

    def _bump_catch_up_refuse(self, reason: str) -> None:
        """Telemetry for catch-up refuse reasons (v1.3.139 / v1.3.146)."""
        r = str(reason or "")
        if r == "catch_up_no_head":
            self._catch_up_no_head_refuse_total = int(
                self._catch_up_no_head_refuse_total or 0
            ) + 1
        elif r == "catch_up_head_height_mismatch":
            self._catch_up_head_height_mismatch_total = int(
                getattr(self, "_catch_up_head_height_mismatch_total", 0) or 0
            ) + 1
        elif r in (
            "catch_up_tip_probe_failed",
            "catch_up_tip_height_mismatch",
        ):
            self._catch_up_tip_probe_refuse_total = int(
                getattr(self, "_catch_up_tip_probe_refuse_total", 0) or 0
            ) + 1
        elif r in (
            "catch_up_peer_head_probe_failed",
            "catch_up_peer_head_hash_mismatch",
            "catch_up_peer_head_height_mismatch",
            "catch_up_peer_head_parent_mismatch",
        ):
            self._catch_up_peer_head_probe_refuse_total = int(
                getattr(self, "_catch_up_peer_head_probe_refuse_total", 0) or 0
            ) + 1
        elif r == "catch_up_tip_head_mismatch":
            self._catch_up_tip_head_mismatch_total = int(
                getattr(self, "_catch_up_tip_head_mismatch_total", 0) or 0
            ) + 1
        elif r == "catch_up_contiguous_parent_mismatch":
            self._catch_up_contiguous_parent_mismatch_total = int(
                getattr(
                    self, "_catch_up_contiguous_parent_mismatch_total", 0
                )
                or 0
            ) + 1
        elif r == "catch_up_height_continuity_mismatch":
            self._catch_up_height_continuity_mismatch_total = int(
                getattr(
                    self, "_catch_up_height_continuity_mismatch_total", 0
                )
                or 0
            ) + 1

    def _catch_up_height_continuity_refuse_reason(
        self, block_data: Dict, expected_h: int
    ) -> str:
        """v1.3.176: catch-up import height must equal expected sync cursor.

        Soft refuse-before-mutate — out-of-order / skip-ahead bodies must not
        force expensive import/reorg. Not tip proof / Long-Range.
        """
        enabled = bool(
            getattr(self.config, "p2p_catch_up_height_continuity_bind", True)
        )
        orch = getattr(self, "catch_up", None)
        if orch is not None:
            return orch.height_continuity_refuse_reason(
                block_data if isinstance(block_data, dict) else {},
                int(expected_h),
                enabled=enabled,
            )
        if not enabled:
            return ""
        if not isinstance(block_data, dict):
            return ""
        try:
            body_h = int(
                block_data.get("height", block_data.get("number", -1)) or -1
            )
            want = int(expected_h)
        except (TypeError, ValueError):
            return ""
        if body_h < 0 or want < 0:
            return ""
        if body_h != want:
            return "catch_up_height_continuity_mismatch"
        return ""

    def _catch_up_contiguous_parent_refuse_reason(
        self, block_data: Dict
    ) -> str:
        """v1.3.175: catch-up import at tip+1 must cite local tip as parent.

        Soft contiguous extension during get_blocks — not tip proof / Long-Range.
        Empty parent / empty tip soft-skips.
        """
        enabled = bool(
            getattr(self.config, "p2p_catch_up_contiguous_parent_bind", True)
        )
        if not enabled:
            return ""
        if not isinstance(block_data, dict):
            return ""
        try:
            body_h = int(
                block_data.get("height", block_data.get("number", -1)) or -1
            )
            tip_h = int(self.blockchain.get_height() or 0)
        except (TypeError, ValueError):
            return ""
        if body_h < 0 or tip_h < 0 or body_h != tip_h + 1:
            return ""
        parent = str(block_data.get("parent_hash") or "").strip()
        local_tip, unreadable = self._try_local_head()
        if unreadable:
            return unreadable
        orch = getattr(self, "catch_up", None)
        if orch is not None:
            return orch.contiguous_parent_refuse_reason(
                block_data, local_tip, enabled=True
            )
        if parent and local_tip and parent.lower() != local_tip.lower():
            return "catch_up_contiguous_parent_mismatch"
        return ""

    def _catch_up_tip_head_refuse_reason(self, peer: PeerConnection) -> str:
        """v1.3.172: after catch-up to peer.height, local tip must match peer.head.

        Soft ownership — height-complete without tip digest is greenwash.
        Not tip proof / Long-Range. Only binds when tip == peer.height
        (exact completion) to avoid racing tip advance false refuses.
        """
        enabled = bool(getattr(self.config, "p2p_catch_up_tip_head_bind", True))
        peer_head = str(getattr(peer, "head", "") or "").strip()
        local_tip, unreadable = self._try_local_head()
        if unreadable:
            return unreadable
        try:
            tip_h = int(self.blockchain.get_height() or 0)
            peer_h = int(getattr(peer, "height", 0) or 0)
        except (TypeError, ValueError):
            tip_h, peer_h = 0, 0
        orch = getattr(self, "catch_up", None)
        if orch is not None:
            return orch.tip_head_at_height_refuse_reason(
                local_height=tip_h,
                peer_height=peer_h,
                local_head=local_tip,
                peer_head=peer_head,
                enabled=enabled,
            )
        if not enabled:
            return ""
        if not peer_head:
            return ""
        if tip_h <= 0 or peer_h <= 0 or tip_h != peer_h:
            return ""
        if local_tip and local_tip.lower() != peer_head.lower():
            return "catch_up_tip_head_mismatch"
        return ""

    async def _catch_up_local_tip_probe_refuse_reason(
        self, peer: PeerConnection
    ) -> str:
        """v1.3.146: before get_blocks, solicit state_root at local tip.

        Soft wire bind — peer must answer for our known tip. Not tip proof /
        root-belongs-to-head crypto / Long-Range checkpoint.
        """
        if not bool(getattr(self.config, "p2p_catch_up_tip_probe", True)):
            return ""
        try:
            local_h = int(self.blockchain.get_height() or 0)
            peer_h = int(getattr(peer, "height", 0) or 0)
        except (TypeError, ValueError):
            return ""
        if peer_h <= local_h or local_h <= 0:
            return ""
        resp = await self.request_peer_state_root(peer, local_h)
        if not resp:
            return "catch_up_tip_probe_failed"
        try:
            rh = int(resp.get("height") or 0)
        except (TypeError, ValueError):
            rh = 0
        if rh and rh != local_h:
            return "catch_up_tip_height_mismatch"
        return ""

    async def _catch_up_peer_head_probe_refuse_reason(
        self, peer: PeerConnection
    ) -> str:
        """v1.3.154: before get_blocks, solicit peer.head via get_block_by_hash.

        v1.3.157: when peer is exactly local+1, parent_hash must match local tip
        (contiguous soft extension — not tip proof / Long-Range).
        """
        if not bool(getattr(self.config, "p2p_catch_up_peer_head_probe", True)):
            return ""
        try:
            local_h = int(self.blockchain.get_height() or 0)
            peer_h = int(getattr(peer, "height", 0) or 0)
        except (TypeError, ValueError):
            return ""
        if peer_h <= local_h:
            return ""
        head = str(getattr(peer, "head", "") or "").strip()
        if not head:
            return ""
        peer_block = await self._request_block_by_hash(peer, head)
        if not peer_block:
            return "catch_up_peer_head_probe_failed"
        got_hash = str(
            peer_block.get("hash") or peer_block.get("block_hash") or ""
        ).strip()
        if got_hash and got_hash.lower() != head.lower():
            return "catch_up_peer_head_hash_mismatch"
        try:
            bh = int(peer_block.get("height", peer_block.get("number", -1)) or -1)
        except (TypeError, ValueError):
            bh = -1
        if bh >= 0 and bh != peer_h:
            return "catch_up_peer_head_height_mismatch"
        # v1.3.157: contiguous (+1) extension must cite our tip as parent.
        if bool(getattr(self.config, "p2p_catch_up_peer_head_parent_bind", True)):
            if peer_h == local_h + 1:
                parent = str(peer_block.get("parent_hash") or "").strip()
                local_tip, unreadable = self._try_local_head()
                if unreadable:
                    return unreadable
                if (
                    parent
                    and local_tip
                    and parent.lower() != local_tip.lower()
                ):
                    return "catch_up_peer_head_parent_mismatch"
        return ""

    async def _fork_peer_head_probe_refuse_reason(
        self, peer: PeerConnection
    ) -> str:
        """v1.3.162: before same-height fork reorg, solicit peer.head on wire.

        Soft wire bind — peer must return a block whose hash matches claimed head
        and height matches claimed peer.height. Not tip proof / Long-Range.

        v1.3.168: probed head parent_hash must match expected tip-height parent
        (same-height sibling soft bind).
        """
        if not bool(getattr(self.config, "p2p_fork_peer_head_probe", True)):
            return ""
        try:
            local_h = int(self.blockchain.get_height() or 0)
            peer_h = int(getattr(peer, "height", 0) or 0)
        except (TypeError, ValueError):
            return ""
        if peer_h != local_h:
            return ""
        head = str(getattr(peer, "head", "") or "").strip()
        if not head:
            return "fork_no_head"
        local_head, unreadable = self._try_local_head()
        if unreadable:
            return unreadable
        if local_head and head.lower() == local_head.lower():
            return ""
        peer_block = await self._request_block_by_hash(peer, head)
        if not peer_block:
            return "fork_peer_head_probe_failed"
        got_hash = str(
            peer_block.get("hash") or peer_block.get("block_hash") or ""
        ).strip()
        if got_hash and got_hash.lower() != head.lower():
            return "fork_peer_head_hash_mismatch"
        try:
            bh = int(peer_block.get("height", peer_block.get("number", -1)) or -1)
        except (TypeError, ValueError):
            bh = -1
        if bh >= 0 and bh != peer_h:
            return "fork_peer_head_height_mismatch"
        # v1.3.168: same-height sibling must share tip-height parent.
        if bool(getattr(self.config, "p2p_fork_peer_head_parent_bind", True)):
            parent = str(peer_block.get("parent_hash") or "").strip()
            local_parent, unreadable = self._try_expected_parent(local_h)
            if unreadable:
                return unreadable
            if (
                parent
                and local_parent
                and local_parent != ("0" * 64)
                and parent.lower() != local_parent.lower()
            ):
                return "fork_peer_head_parent_mismatch"
        return ""

    def _bump_fork_probe_refuse(self, reason: str) -> None:
        r = str(reason or "")
        if r in (
            "fork_no_head",
            "fork_peer_head_probe_failed",
            "fork_peer_head_hash_mismatch",
            "fork_peer_head_height_mismatch",
            "fork_peer_head_parent_mismatch",
        ):
            self._fork_peer_head_probe_refuse_total = int(
                getattr(self, "_fork_peer_head_probe_refuse_total", 0) or 0
            ) + 1

    def _reconcile_fetched_head_refuse_reason(
        self, target_head: str, peer_block: Dict
    ) -> str:
        """v1.3.163: fetched reconcile block hash must match target_head.

        Soft ownership — not tip proof / Long-Range.
        """
        if not bool(getattr(self.config, "p2p_reconcile_head_hash_bind", True)):
            return ""
        want = str(target_head or "").strip()
        if not want or not isinstance(peer_block, dict):
            return ""
        got = str(
            peer_block.get("hash") or peer_block.get("block_hash") or ""
        ).strip()
        if got and got.lower() != want.lower():
            return "reconcile_head_hash_mismatch"
        return ""

    def _reconcile_contiguous_parent_refuse_reason(
        self, peer_block: Dict
    ) -> str:
        """v1.3.165: when fetched head is exactly local+1, parent must match tip.

        Soft contiguous extension — not tip proof / Long-Range.
        """
        if not bool(
            getattr(self.config, "p2p_reconcile_contiguous_parent_bind", True)
        ):
            return ""
        if not isinstance(peer_block, dict):
            return ""
        try:
            body_h = int(
                peer_block.get("height", peer_block.get("number", -1)) or -1
            )
            tip_h = int(self.blockchain.get_height() or 0)
        except (TypeError, ValueError):
            return ""
        if body_h < 0 or tip_h < 0 or body_h != tip_h + 1:
            return ""
        parent = str(peer_block.get("parent_hash") or "").strip()
        local_tip, unreadable = self._try_local_head()
        if unreadable:
            return unreadable
        if parent and local_tip and parent.lower() != local_tip.lower():
            return "reconcile_contiguous_parent_mismatch"
        return ""

    def _reconcile_same_height_parent_refuse_reason(
        self, peer_block: Dict
    ) -> str:
        """v1.3.171: when fetched head is same height as tip, parent must match tip parent.

        Soft tip-sibling ownership — not tip proof / Long-Range.
        """
        if not bool(
            getattr(self.config, "p2p_reconcile_same_height_parent_bind", True)
        ):
            return ""
        if not isinstance(peer_block, dict):
            return ""
        try:
            body_h = int(
                peer_block.get("height", peer_block.get("number", -1)) or -1
            )
            tip_h = int(self.blockchain.get_height() or 0)
        except (TypeError, ValueError):
            return ""
        if body_h < 0 or tip_h < 0 or body_h != tip_h:
            return ""
        got_hash = str(
            peer_block.get("hash") or peer_block.get("block_hash") or ""
        ).strip()
        local_tip, unreadable = self._try_local_head()
        if unreadable:
            return unreadable
        if (
            got_hash
            and local_tip
            and got_hash.lower() == local_tip.lower()
        ):
            return ""
        parent = str(peer_block.get("parent_hash") or "").strip()
        local_parent, unreadable = self._try_expected_parent(tip_h)
        if unreadable:
            return unreadable
        if (
            parent
            and local_parent
            and local_parent != ("0" * 64)
            and parent.lower() != local_parent.lower()
        ):
            return "reconcile_same_height_parent_mismatch"
        return ""

    def _reconcile_tip_head_refuse_reason(self, target_head: str) -> str:
        """v1.3.173: after reconcile import, local tip must match target_head.

        Soft tip digest ownership at reorg choke — not tip proof / Long-Range.
        Empty local tip soft-skips (do not refuse unresolved head).
        """
        if not bool(getattr(self.config, "p2p_reconcile_tip_head_bind", True)):
            return ""
        want = str(target_head or "").strip()
        if not want:
            return ""
        local_tip, unreadable = self._try_local_head()
        if unreadable:
            return unreadable
        if local_tip and local_tip.lower() != want.lower():
            return "reconcile_tip_head_mismatch"
        return ""

    async def _ghost_head_probe_refuse_reason(
        self,
        ghost_head: str,
        peer_hint: Optional[PeerConnection] = None,
    ) -> str:
        """v1.3.164: before GHOST reorg, solicit canonical head on wire.

        Soft wire bind — some peer must return a block whose hash matches
        ghost_head and height matches local tip. Not tip proof / Long-Range.

        v1.3.169: probed head parent_hash must match expected tip-height parent
        (same-height GHOST sibling soft bind).
        """
        if not bool(getattr(self.config, "p2p_ghost_head_probe", True)):
            return ""
        head = str(ghost_head or "").strip()
        if not head:
            return "ghost_no_head"
        local_head, unreadable = self._try_local_head()
        if unreadable:
            return unreadable
        if local_head and head.lower() == local_head.lower():
            return ""
        try:
            local_h = int(self.blockchain.get_height() or 0)
        except (TypeError, ValueError):
            local_h = 0

        peer = self._peer_with_head(head) or peer_hint
        peer_block = None
        if peer:
            peer_block = await self._request_block_by_hash(peer, head)
        if not peer_block:
            for candidate in list(self.peers.values()):
                if peer is not None and candidate is peer:
                    continue
                peer_block = await self._request_block_by_hash(candidate, head)
                if peer_block:
                    break
        if not peer_block:
            return "ghost_head_probe_failed"
        got_hash = str(
            peer_block.get("hash") or peer_block.get("block_hash") or ""
        ).strip()
        if got_hash and got_hash.lower() != head.lower():
            return "ghost_head_hash_mismatch"
        try:
            bh = int(peer_block.get("height", peer_block.get("number", -1)) or -1)
        except (TypeError, ValueError):
            bh = -1
        if bh >= 0 and bh != local_h:
            return "ghost_head_height_mismatch"
        # v1.3.169: same-height GHOST sibling must share tip-height parent.
        if bool(getattr(self.config, "p2p_ghost_head_parent_bind", True)):
            parent = str(peer_block.get("parent_hash") or "").strip()
            local_parent, unreadable = self._try_expected_parent(local_h)
            if unreadable:
                return unreadable
            if (
                parent
                and local_parent
                and local_parent != ("0" * 64)
                and parent.lower() != local_parent.lower()
            ):
                return "ghost_head_parent_mismatch"
        return ""

    def _bump_ghost_probe_refuse(self, reason: str) -> None:
        r = str(reason or "")
        if r in (
            "ghost_no_head",
            "ghost_head_probe_failed",
            "ghost_head_hash_mismatch",
            "ghost_head_height_mismatch",
            "ghost_head_parent_mismatch",
        ):
            self._ghost_head_probe_refuse_total = int(
                getattr(self, "_ghost_head_probe_refuse_total", 0) or 0
            ) + 1

    async def _reconcile_ghost_head(
        self,
        ghost_head: str,
        peer_hint: Optional[PeerConnection] = None,
    ) -> bool:
        """Probe ghost_head on wire, then reorg via ForkReconcileService."""
        from sync.fork import ForkReconcileStatus

        outcome = await self._fork_reconcile_run_to_head(
            ghost_head, peer_hint=peer_hint, ghost_probe=True
        )
        if outcome is None:
            return False
        return outcome.status is ForkReconcileStatus.COMPLETE

    def _schedule_sync(self, peer: PeerConnection) -> None:
        """Coalesce duplicate sync tasks per peer (v1.3.66) + global inflight cap (v1.3.72)."""
        refuse = self._catch_up_ahead_refuse_reason(peer)
        if refuse:
            self._bump_catch_up_refuse(refuse)
            logger.debug(
                "[P2P] catch-up refuse %s peer=%s height=%s",
                refuse,
                (peer.peer_id or "")[:12],
                getattr(peer, "height", 0),
            )
            return
        key = str(peer.peer_id or self._peer_key(peer) or id(peer))
        existing = self._sync_tasks.get(key)
        if existing is not None and not existing.done():
            return
        # Global sync admission: avoid N-peer catch-up flooding serial apply queue.
        max_n = max(1, int(getattr(self.config, "p2p_max_sync_inflight", 2) or 2))
        active = sum(1 for t in self._sync_tasks.values() if t and not t.done())
        if active >= max_n:
            self._sync_admission_rejects = int(self._sync_admission_rejects or 0) + 1
            logger.debug(
                "[P2P] sync admission reject (active=%s max=%s peer=%s)",
                active,
                max_n,
                key[:16],
            )
            return
        task = asyncio.create_task(self._sync_with_peer_safe(peer))
        self._sync_tasks[key] = task

        def _cleanup(_t, k=key):
            cur = self._sync_tasks.get(k)
            if cur is _t:
                self._sync_tasks.pop(k, None)

        task.add_done_callback(_cleanup)

    def _schedule_connect(self, host: str, port: int) -> None:
        """Coalesce duplicate connect tasks (v1.3.66)."""
        key = f"{host}:{int(port)}"
        existing = self._connect_tasks.get(key)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(self.connect_peer(host, int(port)))
        self._connect_tasks[key] = task

        def _cleanup(_t, k=key):
            cur = self._connect_tasks.get(k)
            if cur is _t:
                self._connect_tasks.pop(k, None)

        task.add_done_callback(_cleanup)

    async def _sync_with_peer_safe(self, peer: PeerConnection):
        lock = self._peer_lock(peer.peer_id or f"{peer.host}:{peer.port}")
        async with lock:
            try:
                await self._sync_with_peer(peer)
            except Exception as e:
                self._sync_fail = int(self._sync_fail or 0) + 1
                print(f"[P2P] Sync error via {peer.peer_id[:8]}: {e}")
                logger.exception("[P2P] sync failed")

    def _mempool_solicit_armed_for(self, peer: PeerConnection) -> bool:
        """v1.3.144: True only while a mempool pull waiter is armed for this peer.

        Soft DoS honesty — not anti-Sybil / tip proof. Native shell skips batch
        ECDSA for unsolicited MSG_MEMPOOL when False.
        """
        pid = getattr(peer, "peer_id", "") or ""
        if not pid:
            return False
        hub = getattr(self, "solicit_hub", None)
        if hub is None:
            return False
        return bool(hub.mempool_solicit_armed(pid))

    def _stash_late_state_root(self, peer: PeerConnection, data: Any) -> bool:
        """Keep a just-timed-out state_root payload instead of unsolicited strike.

        Waiter is already popped on asyncio timeout; the reply is often already
        in the native buffer (miner HOL). Stash for the 400ms grace in
        ``_wait_peer_response`` so STRICT HTTP 8s can still score the wire.
        """
        pid = str(getattr(peer, "peer_id", "") or "")
        if not pid or not isinstance(data, dict):
            return False
        marked = float((getattr(self, "_state_root_timeout_at", {}) or {}).get(pid, 0.0) or 0.0)
        if marked <= 0.0 or (time.monotonic() - marked) > 2.0:
            return False
        late = getattr(self, "_state_root_late", None)
        if late is None:
            self._state_root_late = {}
            late = self._state_root_late
        late[pid] = (data, time.monotonic())
        self._state_root_late_accepts_total = int(
            getattr(self, "_state_root_late_accepts_total", 0) or 0
        ) + 1
        return True

    def _consume_late_state_root(self, peer: PeerConnection) -> Optional[Dict]:
        """Use a stashed late reply instead of a second RTT (retry)."""
        pid = str(getattr(peer, "peer_id", "") or "")
        if not pid:
            return None
        late = (getattr(self, "_state_root_late", {}) or {}).pop(pid, None)
        if not late:
            return None
        data, ts = late
        if isinstance(data, dict) and (time.monotonic() - float(ts or 0.0)) < 2.0:
            return data
        return None

    def _solicit_lock_for(self, peer_id: str, kind: str = "") -> asyncio.Lock:
        locks = getattr(self, "_solicit_peer_locks", None)
        if locks is None:
            self._solicit_peer_locks = {}
            locks = self._solicit_peer_locks
        key = f"{peer_id}\x1f{kind or '_'}"
        lock = locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            locks[key] = lock
        return lock

    async def _wait_peer_response(
        self,
        peer: PeerConnection,
        expected_types: tuple,
        timeout: float = 30,
        presend=None,
        request_ctx: Optional[Dict] = None,
    ) -> Optional[Dict]:
        hub = getattr(self, "solicit_hub", None)
        if hub is None:
            raise RuntimeError("solicit_hub required for peer response wait")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        kind = ""
        if isinstance(request_ctx, dict):
            kind = str(request_ctx.get("kind") or "")
        pid = str(peer.peer_id or "")
        async with self._solicit_lock_for(pid, kind):
            hub.arm(peer.peer_id, expected_types, fut, request_ctx)
        sent = True
        if presend:
            sent = await presend()
        try:
            if sent is False:
                # Response may already have landed while send() awaited the
                # ctrl-queue Future. Do not timeout a completed waiter.
                if fut.done() and not fut.cancelled():
                    return fut.result()
                late = self._consume_late_state_root(peer) if MSG_STATE_ROOT_RESPONSE in tuple(expected_types or ()) else None
                if late:
                    return {"type": MSG_STATE_ROOT_RESPONSE, "data": late}
                hub.timeout(pid, result=None, kind=kind, fut=fut)
                return None
            if pid and self.peers.get(pid) is not peer:
                hub.timeout(pid, result=None, kind=kind, fut=fut)
                return None
            # Wait outside the lock so mempool/catch-up cannot block HTTP 8s.
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            want_root = MSG_STATE_ROOT_RESPONSE in tuple(expected_types or ())
            if want_root:
                self._state_root_timeout_at[pid] = time.monotonic()
            hub.timeout(pid, result=None, kind=kind, fut=fut)
            if want_root:
                await asyncio.sleep(0.4)
                late = (getattr(self, "_state_root_late", {}) or {}).pop(pid, None)
                if late:
                    data, ts = late
                    if (
                        isinstance(data, dict)
                        and (time.monotonic() - float(ts or 0.0)) < 2.0
                    ):
                        return {"type": MSG_STATE_ROOT_RESPONSE, "data": data}
            return None
        finally:
            hub.clear(peer.peer_id, kind=kind, fut=fut)

    def _expected_parent_for_height(self, height: int) -> str:
        """Parent digest expected for the first block at `height`."""
        if int(height) <= 0:
            return "0" * 64
        prev = self.blockchain.get_block(int(height) - 1)
        if isinstance(prev, dict):
            h = str(prev.get("hash") or prev.get("block_hash") or "").strip()
            if h:
                return h
        tip = (self.head() or "").strip()
        return tip or ("0" * 64)

    async def _sync_with_peer(self, peer: PeerConnection):
        """Догоняем пира если он выше нас, или выравниваем форк на той же высоте."""
        our_height = self.blockchain.get_height()
        if peer.height < our_height:
            return
        if peer.height == our_height:
            local_head = self.head() or ""
            peer_head = peer.head or ""
            if peer_head and local_head != peer_head:
                await self._reconcile_fork_at_peer(peer)
            elif self.sync_engine:
                await self.refresh_consistency()
            await self._sync_mempool_with_peer(peer)
            return

        # v1.3.139: height-only ahead without peer.head — refuse get_blocks catch-up.
        # v1.3.146: also head↔height local bind.
        refuse = self._catch_up_ahead_refuse_reason(peer)
        if refuse:
            self._bump_catch_up_refuse(refuse)
            logger.info(
                "[P2P] catch-up refuse %s peer=%s claimed_height=%s",
                refuse,
                (peer.peer_id or "")[:12],
                peer.height,
            )
            return

        # v1.3.146: solicit local-tip state_root before downloading ahead blocks.
        tip_refuse = await self._catch_up_local_tip_probe_refuse_reason(peer)
        if tip_refuse:
            self._bump_catch_up_refuse(tip_refuse)
            logger.info(
                "[P2P] catch-up tip-probe refuse %s peer=%s local_height=%s",
                tip_refuse,
                (peer.peer_id or "")[:12],
                self.blockchain.get_height() if self.blockchain else 0,
            )
            return

        # v1.3.154: solicit peer.head block before downloading ahead range.
        head_refuse = await self._catch_up_peer_head_probe_refuse_reason(peer)
        if head_refuse:
            self._bump_catch_up_refuse(head_refuse)
            logger.info(
                "[P2P] catch-up peer-head probe refuse %s peer=%s head=%s",
                head_refuse,
                (peer.peer_id or "")[:12],
                (getattr(peer, "head", "") or "")[:16],
            )
            return

        if self.sync_engine:
            self.sync_engine.add_peer(peer)

        # ADR 0004 Step B: ahead batch loop delegated to CatchUpPathAService
        # via thin P2P adapters. All policy, import, reorg, and tip-head logic
        # lives in the domain layer; P2P keeps TCP ownership only.
        from network.catchup_adapters import build_path_a_adapters
        from sync.catchup import CatchUpConfig, CatchUpPathAService, CatchUpPeerView, CatchUpStatus

        _loop = asyncio.get_running_loop()
        _chain_a, _fetch_a, _probe_a, _side_a = build_path_a_adapters(self, peer, _loop)
        _svc = CatchUpPathAService(
            chain=_chain_a,
            fetch=_fetch_a,
            probe=_probe_a,
            side=_side_a,
            orchestrator=getattr(self, "catch_up", None),
        )
        _peer_view = CatchUpPeerView(
            peer_id=str(peer.peer_id or ""),
            height=int(getattr(peer, "height", 0) or 0),
            head_hash=str(getattr(peer, "head", "") or ""),
        )
        _cfg = CatchUpConfig(
            batch_size=max(1, int(self.config.sync_batch_size or 32)),
            require_head=bool(getattr(self.config, "p2p_catch_up_require_head", True)),
            tip_head_bind=bool(getattr(self.config, "p2p_catch_up_tip_head_bind", True)),
            height_continuity_bind=bool(
                getattr(self.config, "p2p_catch_up_height_continuity_bind", True)
            ),
            contiguous_parent_bind=bool(
                getattr(self.config, "p2p_catch_up_contiguous_parent_bind", True)
            ),
            tip_probe_enabled=bool(getattr(self.config, "p2p_catch_up_tip_probe", True)),
            peer_head_probe_enabled=bool(
                getattr(self.config, "p2p_catch_up_peer_head_probe", True)
            ),
            fetch_timeout=45.0,
        )
        # Serialize PathA across peers: two ahead peers must not interleave
        # import(#340) + reorg(#339) on the serial apply queue.
        async with self._global_catch_up_lock():
            outcome = await asyncio.to_thread(_svc.run_ahead, _peer_view, _cfg)

        reached_target = outcome.reached_target
        if not reached_target and outcome.status is not CatchUpStatus.SKIPPED:
            self._sync_fail = int(self._sync_fail or 0) + 1
        logger.info(
            "[P2P] CatchUpPathA peer=%s status=%s imported=%d reached=%s",
            (peer.peer_id or "")[:12],
            outcome.status.value,
            outcome.imported,
            reached_target,
        )

        if self.sync_engine:
            await self.refresh_consistency()

        # Never raise state-root baseline after a stalled/incomplete sync —
        # that would greenwash partial catch-up as a new strict tip.
        tip = self.blockchain.get_height()
        if reached_target and hasattr(self.blockchain, "set_state_root_baseline"):
            self.blockchain.set_state_root_baseline(tip)
            print(f"[P2P] State-root baseline set to #{tip} (strict above)")

        await self._sync_mempool_with_peer(peer)

    async def _reconcile_to_head_hash(
        self,
        target_head: str,
        peer_hint: Optional[PeerConnection] = None,
    ) -> bool:
        """Reorg to target head hash via ForkReconcileService (ADR 0005)."""
        target_head = (target_head or "").strip()
        if not target_head:
            return False
        outcome = await self._fork_reconcile_run_to_head(
            target_head, peer_hint=peer_hint, ghost_probe=False
        )
        if outcome is None:
            return False
        if outcome.status.value == "complete":
            peer = peer_hint
            if peer is None:
                peer = self._peer_with_head(target_head)
            if peer is not None:
                try:
                    tip = int(self.blockchain.get_height() or 0)
                    ph = int(getattr(peer, "height", 0) or 0)
                except (TypeError, ValueError):
                    tip, ph = 0, 0
                if ph > tip:
                    await self._sync_with_peer_safe(peer)
            return True
        return bool(outcome.ok and outcome.status.value == "skipped")

    async def _reconcile_fork_at_peer(self, peer: PeerConnection) -> bool:
        """Same height, different head — thin wire to ForkReconcileService."""
        from network.fork_adapters import build_fork_reconcile_adapters
        from sync.fork import (
            ForkPeerView,
            ForkReconcileConfig,
            ForkReconcileMaliciousError,
            ForkReconcileService,
            ForkReconcileStatus,
        )

        loop = asyncio.get_running_loop()
        chain_a, fetch_a, probe_a, side_a = build_fork_reconcile_adapters(
            self, peer, loop
        )
        svc = ForkReconcileService(
            chain=chain_a, fetch=fetch_a, probe=probe_a, side=side_a
        )
        view = ForkPeerView(
            peer_id=str(peer.peer_id or ""),
            height=int(getattr(peer, "height", 0) or 0),
            head_hash=str(getattr(peer, "head", "") or ""),
        )
        cfg = ForkReconcileConfig(
            fork_probe_enabled=bool(
                getattr(self.config, "p2p_fork_peer_head_probe", True)
            ),
            ghost_probe_enabled=bool(
                getattr(self.config, "p2p_ghost_head_probe", True)
            ),
            prefer_ghost=True,
            head_hash_bind=bool(
                getattr(self.config, "p2p_reconcile_head_hash_bind", True)
            ),
            contiguous_parent_bind=bool(
                getattr(self.config, "p2p_reconcile_contiguous_parent_bind", True)
            ),
            same_height_parent_bind=bool(
                getattr(self.config, "p2p_reconcile_same_height_parent_bind", True)
            ),
            tip_head_bind=bool(
                getattr(self.config, "p2p_reconcile_tip_head_bind", True)
            ),
            fetch_timeout=30.0,
        )
        try:
            outcome = await asyncio.to_thread(svc.run_same_height, view, cfg)
        except ForkReconcileMaliciousError as exc:
            logger.warning(
                "[P2P] ForkReconcile FAIL-CLOSED peer=%s reason=%s evidence=%s",
                (peer.peer_id or "")[:12],
                exc.outcome.reason_code,
                getattr(exc.evidence, "reason_code", ""),
            )
            return False
        logger.info(
            "[P2P] ForkReconcile peer=%s status=%s reason=%s",
            (peer.peer_id or "")[:12],
            outcome.status.value,
            outcome.reason_code,
        )
        if outcome.status is ForkReconcileStatus.COMPLETE:
            try:
                tip = int(self.blockchain.get_height() or 0)
                ph = int(getattr(peer, "height", 0) or 0)
            except (TypeError, ValueError):
                tip, ph = 0, 0
            if ph > tip:
                await self._sync_with_peer_safe(peer)
            return True
        return bool(outcome.ok)

    async def _fork_reconcile_run_to_head(
        self,
        target_head: str,
        *,
        peer_hint: Optional[PeerConnection] = None,
        ghost_probe: bool = False,
    ):
        """Shared thin wire for run_to_head (GHOST / admin / peer tip)."""
        from network.fork_adapters import build_fork_reconcile_adapters
        from sync.fork import (
            ForkPeerView,
            ForkReconcileConfig,
            ForkReconcileMaliciousError,
            ForkReconcileService,
        )

        peer = peer_hint
        if peer is None:
            peer = self._peer_with_head(target_head)
        loop = asyncio.get_running_loop()
        chain_a, fetch_a, probe_a, side_a = build_fork_reconcile_adapters(
            self, peer, loop
        )
        svc = ForkReconcileService(
            chain=chain_a, fetch=fetch_a, probe=probe_a, side=side_a
        )
        view = ForkPeerView(
            peer_id=str(getattr(peer, "peer_id", "") or "") if peer else "",
            height=int(getattr(peer, "height", 0) or 0) if peer else 0,
            head_hash=str(getattr(peer, "head", "") or "") if peer else "",
        )
        cfg = ForkReconcileConfig(
            fork_probe_enabled=bool(
                getattr(self.config, "p2p_fork_peer_head_probe", True)
            ),
            ghost_probe_enabled=bool(
                getattr(self.config, "p2p_ghost_head_probe", True)
            ),
            prefer_ghost=True,
            head_hash_bind=bool(
                getattr(self.config, "p2p_reconcile_head_hash_bind", True)
            ),
            contiguous_parent_bind=bool(
                getattr(self.config, "p2p_reconcile_contiguous_parent_bind", True)
            ),
            same_height_parent_bind=bool(
                getattr(self.config, "p2p_reconcile_same_height_parent_bind", True)
            ),
            tip_head_bind=bool(
                getattr(self.config, "p2p_reconcile_tip_head_bind", True)
            ),
            fetch_timeout=30.0,
        )
        try:
            return await asyncio.to_thread(
                lambda: svc.run_to_head(
                    str(target_head or ""),
                    view,
                    cfg,
                    ghost_probe=bool(ghost_probe),
                )
            )
        except ForkReconcileMaliciousError as exc:
            logger.warning(
                "[P2P] ForkReconcile FAIL-CLOSED to_head reason=%s",
                exc.outcome.reason_code,
            )
            return exc.outcome


    async def reconcile_peers(self) -> Dict:
        """Align chain tips with connected peers (height + head + state_root)."""
        results = []
        for peer in list(self.peers.values()):
            entry = {"peer": peer.peer_id[:12], "ok": False}
            try:
                if peer.height > self.blockchain.get_height():
                    await self._sync_with_peer_safe(peer)
                    entry["ok"] = True
                    entry["action"] = "catch_up"
                elif peer.height == self.blockchain.get_height():
                    local_head = self.head() or ""
                    ghost_head = self._ghost_canonical_head()
                    if ghost_head and ghost_head.lower() != local_head.lower():
                        entry["ok"] = await self._reconcile_ghost_head(
                            ghost_head, peer_hint=peer
                        )
                        entry["action"] = "ghost_reorg"
                    elif (peer.head or "") != local_head:
                        entry["ok"] = await self._reconcile_fork_at_peer(peer)
                        entry["action"] = "fork_reorg"
                    else:
                        entry["ok"] = True
                        entry["action"] = "already_aligned"
                else:
                    entry["ok"] = True
                    entry["action"] = "ahead_of_peer"
                if abs(int(peer.height or 0) - int(self.blockchain.get_height() or 0)) <= 2:
                    await self._sync_mempool_with_peer(peer, timeout=3)
            except Exception as exc:
                entry["error"] = str(exc)
            results.append(entry)

        if self.sync_engine:
            await self.refresh_consistency()
        elif self.peers:
            # Reconcile "ok" without a SyncEngine must not leave stale mesh-green.
            self.force_inconsistent("no_sync_engine_with_peers")

        return {
            "reconciled": results,
            "state_consistent": self._state_consistent,
            "height": self.blockchain.get_height(),
            "head": self.head() or "",
            "ghost_head": self._ghost_canonical_head() or "",
            "state_root": self.blockchain.get_state_root() if self.blockchain else "",
        }

    def trigger_reconcile(self) -> None:
        """Schedule peer reconcile from REST thread."""
        if not self._loop or not self._running:
            return
        asyncio.run_coroutine_threadsafe(self.reconcile_peers(), self._loop)

    def _remember_addr(self, addr: str) -> None:
        """Remember a reconnect candidate as host:port.

        Skip bare IP literals — docker bridge IPs cause dual-dial storms when the
        same peer is already live via a hostname bootstrap seed.
        """
        want = self._normalize_dial_addr(addr)
        if not want:
            return
        host, _, _port = want.partition(":")
        if self._is_ip_literal(host):
            return
        self.peer_manager.remember_addr(want)

    @staticmethod
    def _is_ip_literal(host: str) -> bool:
        h = str(host or "").strip().strip("[]")
        if not h:
            return False
        parts = h.split(".")
        if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            return True
        return ":" in h  # IPv6

    def _bind_bootstraps_for_peer(self, peer: PeerConnection) -> None:
        """Map configured bootstrap seeds to this peer_id when host/id align."""
        pid = str(getattr(peer, "peer_id", "") or "").strip()
        if not pid:
            return
        dial = self._normalize_dial_addr(str(getattr(peer, "dial_target", "") or ""))
        if dial:
            self._bind_bootstrap_peer(dial, pid)
        for raw in list(getattr(self.config, "bootstrap_peers", []) or []):
            want = self._normalize_dial_addr(str(raw).strip())
            if not want:
                continue
            host, _, _p = want.partition(":")
            if self._bootstrap_host_matches_peer_id(host, pid):
                self._bind_bootstrap_peer(want, pid)

    @staticmethod
    def _host_looks_like_libp2p_peer_id(host: str) -> bool:
        """True when *host* is a rust-libp2p PeerId, not a dialable DNS/IP.

        Discovery/reconnect must not emit ``/dns4/<PeerId>/tcp/5000`` — that
        strikes the peer and is never a valid industrial mesh address.
        """
        h = str(host or "").strip()
        if h.startswith("12D3KooW") or h.startswith("12D3Koo"):
            return True
        if h.startswith("Qm") and len(h) >= 46 and ":" not in h:
            return True
        return False

    @staticmethod
    def _bootstrap_host_matches_peer_id(host: str, peer_id: str) -> bool:
        """Best-effort: node2 ↔ docker-prod-mesh-2 / *-2."""
        h = str(host or "").strip().lower()
        pid = str(peer_id or "").strip().lower()
        if not h or not pid:
            return False
        if h.startswith("node") and h[4:].isdigit():
            n = h[4:]
            return pid.endswith(f"-{n}") or pid == f"node{n}"
        return h == pid

    def _prune_stale_peers(self, max_age: Optional[float] = None) -> int:
        """Drop stale or critically unhealthy peer objects before reconnect/dedup."""
        local_height = int(self.blockchain.get_height() or 0) if self.blockchain else 0
        removed = self.peer_manager.prune_stale(
            local_height=local_height,
            max_age=max_age,
        )
        self._eclipse_prune_total = int(self.peer_manager.eclipse.prune_total or 0)
        self._eclipse_at_risk = 1 if self.peer_manager.eclipse.at_risk else 0
        self._eclipse_ratio = float(self.peer_manager.eclipse.eclipse_ratio or 0)
        self._eclipse_unique_public_subnets = int(
            self.peer_manager.eclipse.unique_public_subnets or 0
        )
        self._eclipse_public_peers = int(self.peer_manager.eclipse.public_peers or 0)
        return removed

    async def reconnect_known_peers(self) -> Dict:
        """Actively reconnect bootstrap/known peers and report the result."""
        pruned = self._prune_stale_peers()
        candidates = []
        for addr in list(getattr(self.config, "bootstrap_peers", []) or []) + list(self._known_addrs):
            if addr not in candidates:
                candidates.append(addr)

        before = self.peer_count()
        if not candidates:
            return {
                "ok": before > 0,
                "before": before,
                "after": before,
                "attempts": [],
                "known_addresses": list(self._known_addrs),
                "message": "no known peer addresses",
            }
        attempts = []
        for addr in candidates:
            parts = str(addr).rsplit(":", 1)
            if len(parts) != 2:
                continue
            host, port_s = parts
            try:
                port = int(port_s)
            except (TypeError, ValueError):
                attempts.append({"address": addr, "ok": False, "error": "bad_port"})
                continue
            already_peer = next(
                (
                    p
                    for p in self.peers.values()
                    if p.host == host and (p.port == port or p.listen_port == port)
                ),
                None,
            )
            if already_peer:
                ok_send = await already_peer.send(
                    MSG_STATUS,
                    {
                        "height": self.blockchain.get_height(),
                        "head_hash": self.head() or "",
                    },
                    wait=True,
                )
                if not ok_send:
                    self._peer_status_send_fail = int(self._peer_status_send_fail or 0) + 1
                    logger.warning("[P2P] status refresh to %s failed", addr)
                attempts.append({
                    "address": addr,
                    "ok": bool(ok_send),
                    "action": "already_connected_status_refresh",
                })
                continue
            ok = await self.connect_peer(host, port)
            attempts.append({"address": addr, "ok": bool(ok), "action": "connect"})

        await asyncio.sleep(0.5)
        return {
            "ok": self.peer_count() >= before,
            "before": before,
            "after": self.peer_count(),
            "attempts": attempts,
            "known_addresses": list(self._known_addrs),
            "pruned_stale": pruned,
        }

    def reconnect_known_peers_sync(self, timeout: float = 20) -> Dict:
        """Thread-safe reconnect entrypoint for REST/scripts."""
        if not self._loop or not self._running:
            return {"ok": False, "error": "p2p not running"}
        try:
            return asyncio.run_coroutine_threadsafe(
                self.reconnect_known_peers(), self._loop
            ).result(timeout=timeout)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "after": self.peer_count()}

    def _cap_claimed_peer_height(self, claimed_h: int) -> tuple:
        """Return (owned_height, was_capped) using p2p_max_peer_height_ahead.

        Soft scheduling bound only — not tip proof / fork-choice.
        """
        try:
            claimed = int(claimed_h or 0)
        except (TypeError, ValueError):
            return 0, False
        if claimed <= 0:
            return 0, False
        local_h = int(self.blockchain.get_height() or 0)
        max_ahead = int(
            getattr(self.config, "p2p_max_peer_height_ahead", 100_000) or 100_000
        )
        if max_ahead <= 0:
            return claimed, False
        ceiling = local_h + max_ahead
        if claimed > ceiling:
            return ceiling, True
        return claimed, False

    def _state_root_request_ctx(self, height: int) -> Dict:
        """v1.3.135: bind expected head/root from local tip or known historical header."""
        tip = int(self.blockchain.get_height() or 0)
        h = tip if int(height) <= 0 else int(height)
        ctx: Dict = {"kind": "state_root", "height": h, "expected_head": "", "expected_state_root": ""}
        if h == tip:
            ctx["expected_head"] = str(self.head() or "")
            ctx["expected_state_root"] = str(self.blockchain.get_state_root() or "")
            return ctx
        if h > tip:
            return ctx
        blk = self.blockchain.get_block(h)
        if isinstance(blk, dict):
            ctx["expected_head"] = str(blk.get("hash") or blk.get("block_hash") or "")
            ctx["expected_state_root"] = str(blk.get("state_root") or "")
        return ctx

    def _state_root_solicit_height(
        self,
        peer: PeerConnection,
        height: Optional[int] = None,
    ) -> int:
        """Height to solicit from `peer`.

        Ask local tip. Do not cap at stale ``peer.height``: that turned a
        same-chain probe into a historical lag reply, and ConsistencyMachine
        skipped ``peer_h < local_height`` as no_same_height_match (consist=False
        while /status heights already matched). Ahead requests are answered
        with a lag tip (handlers), not a silent refuse.
        """
        if height is None:
            local = int(self.blockchain.get_height() or 0)
        else:
            local = int(height)
        if local < 0:
            local = 0
        return local

    def note_local_forge(self, hold_sec: float = 1.0, height: int = 0) -> None:
        """Defer state_root solicit until NEW_BLOCK is on the wire.

        Mining used to ``create_task(broadcast)`` then immediately
        ``sync_state``; the probe raced broadcast HOL and returned empty
        with 2 live peers (5h STRICT 18180). Delay, do not skip.

        ``height`` is the just-forged tip. Echo of that block (or tip+1 still
        in the pipeline) must not hit tip_unknown_parent against a stale
        ``get_chain_tip`` read from another thread.
        """
        hold = max(0.0, min(2.0, float(hold_sec)))
        self._wire_probe_hold_until = time.monotonic() + hold
        try:
            h = int(height or 0)
        except (TypeError, ValueError):
            h = 0
        if h > 0:
            prev = int(getattr(self, "_last_local_forge_height", 0) or 0)
            if h > prev:
                self._last_local_forge_height = h
            shadow = getattr(self, "tip_safety_shadow", None)
            note_shadow = getattr(shadow, "note_local_forge", None)
            if callable(note_shadow):
                note_shadow(h)

    async def _wait_wire_probe_gate(self, timeout: float = 1.2) -> float:
        """Wait until apply-queue idle and post-forge hold expires.

        Bounded so HTTP STRICT 8s still has budget for the 6.5s RTT.
        """
        t0 = time.monotonic()
        deadline = t0 + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            q = getattr(self, "apply_queue", None)
            if q is not None:
                maxsize = int(getattr(q, "maxsize", 0) or 0)
                depth = int(getattr(q, "depth", 0) or 0)
                # Saturated apply queue: refuse to stall HTTP / harness (15s /status).
                if maxsize > 0 and depth >= maxsize:
                    break
            apply_busy = bool(q is not None and getattr(q, "busy", False))
            hold = float(getattr(self, "_wire_probe_hold_until", 0.0) or 0.0)
            if not apply_busy and hold <= time.monotonic():
                break
            await asyncio.sleep(0.05)
        return time.monotonic() - t0

    def _state_root_probe_lock_obj(self) -> asyncio.Lock:
        lock = getattr(self, "_state_root_probe_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._state_root_probe_lock = lock
        return lock

    async def _coalesced_peer_state_roots(self) -> List[Dict]:
        """Single in-flight state_root gather; concurrent waiters join it."""
        # Isolated node: return immediately. Joining a stale flight after the
        # last peer dropped made HTTP 8s timeout (full1 peer_probe_ok).
        if not self.peers:
            return []
        async with self._state_root_probe_lock_obj():
            if not self.peers:
                return []
            existing = getattr(self, "_state_root_probe_task", None)
            if existing is not None and not existing.done():
                task = existing
            else:
                # Shared flight must finish inside the HTTP 8s STRICT budget.
                # 3.5s was shorter than miner HOL: 5h STRICT soak on 18180 saw
                # solicit_timeouts≈late_accepts (reply after waiter) and empty
                # wire. 6.5s + 0.4s grace stays under 8s; retry=True still
                # doubles RTT past quick/STRICT. Coalesced state_root flight is one RTT;
                # late stash covers HOL past the waiter.
                await self._wait_wire_probe_gate(1.2)
                task = asyncio.create_task(
                    self.request_peer_state_roots(
                        per_peer_timeout=6.5,
                        retry=False,
                    )
                )
                self._state_root_probe_task = task

                def _cleanup(_t, owner=task):
                    if getattr(self, "_state_root_probe_task", None) is owner:
                        self._state_root_probe_task = None
                    self._apply_completed_wire_probe(_t)

                task.add_done_callback(_cleanup)
        return await task

    def _apply_completed_wire_probe(self, task: asyncio.Task) -> None:
        """Feed a finished coalesced flight into ConsistencyService.

        HTTP/sync waiters that hit future.result timeout must not leave
        topology_healthy false after the wire actually answered.
        """
        if task.cancelled():
            return
        try:
            roots = task.result()
        except Exception as exc:
            logger.warning("[P2P] coalesced wire probe task failed: %s", exc)
            return
        if not isinstance(roots, list) or not roots:
            return
        eng = getattr(self, "sync_engine", None)
        if eng is None or not hasattr(eng, "consistency"):
            return
        try:
            from sync.consistency import WireProbeResult

            bc = self.blockchain
            local_root = str(bc.get_state_root() or "")
            local_height = int(bc.get_height() or 0)
            peers = eng._peer_views() if hasattr(eng, "_peer_views") else ()
            probe = WireProbeResult.succeeded(wire_roots=tuple(roots))
            eng.consistency.apply_probe_evaluation(
                peers=peers,
                local_height=local_height,
                local_root=local_root,
                probe=probe,
            )
            if hasattr(eng, "_set_state_consistent"):
                eng._set_state_consistent(
                    bool(eng.consistency.snapshot().consistent)
                )
            eng._wire_probe_fail_ts = 0.0
        except Exception as exc:
            logger.warning("[P2P] apply completed wire probe suppressed: %s", exc)

    def _state_root_response_for_height(self, req_h: int) -> Optional[Dict]:
        """v1.3.129: build honest state_root_response for a requested height.

        Tip → live root + head. Historical → block header root/hash.
        Ahead of tip / missing incomplete headers → None (refuse, never mislabel tip).
        """
        tip = int(self.blockchain.get_height() or 0)
        height = tip if int(req_h) <= 0 else int(req_h)
        if height > tip:
            return None
        # Empty follower tip (no block #0 yet): never advertise a synthetic root.
        get_last = getattr(self.blockchain, "get_last_block", None)
        if callable(get_last):
            try:
                if get_last() is None:
                    return None
            except Exception as exc:
                logger.warning(
                    "[P2P] get_last_block failed in state_root_response; refuse: %s",
                    exc,
                )
                return None
        if height == tip:
            return {
                "height": tip,
                "state_root": self.blockchain.get_state_root(),
                "head_hash": self.head() or "",
            }
        blk = self.blockchain.get_block(height)
        if not isinstance(blk, dict):
            return None
        root = str(blk.get("state_root") or "").strip()
        head = str(blk.get("hash") or blk.get("block_hash") or "").strip()
        if not root or not head:
            return None
        return {
            "height": height,
            "state_root": root,
            "head_hash": head,
        }

    async def request_peer_state_root(
        self,
        peer: PeerConnection,
        height: int = None,
        *,
        timeout: float = 30,
        retry: bool = True,
    ) -> Optional[Dict]:
        """Request state_root at height from a single peer."""
        # Previous flight timed out; the reply landed after hub.clear() and
        # was stashed. Use it before another RTT (stash TTL is 2s; harness
        # interval / sync backoff are longer, so this is same-burst only).
        stashed = self._consume_late_state_root(peer)
        if stashed:
            return stashed
        h = self._state_root_solicit_height(peer, height)
        wait_s = max(0.4, float(timeout))
        msg = await self._wait_peer_response(
            peer,
            (MSG_STATE_ROOT_RESPONSE,),
            timeout=wait_s,
            presend=lambda: peer.send(MSG_STATE_ROOT_REQUEST, {"height": h}),
            request_ctx=self._state_root_request_ctx(int(h)),
        )
        if not msg or msg.get("type") != MSG_STATE_ROOT_RESPONSE:
            # Late stash even when retry=False — retry used to be the only
            # consume path, so one-RTT flights dropped HOL replies.
            late = self._consume_late_state_root(peer)
            if late:
                return late
            if retry:
                msg = await self._wait_peer_response(
                    peer,
                    (MSG_STATE_ROOT_RESPONSE,),
                    timeout=wait_s,
                    presend=lambda: peer.send(MSG_STATE_ROOT_REQUEST, {"height": h}),
                    request_ctx=self._state_root_request_ctx(int(h)),
                )
        if not msg or msg.get("type") != MSG_STATE_ROOT_RESPONSE:
            return None
        data = msg.get("data")
        return data if isinstance(data, dict) else None

    async def request_peer_state_roots(
        self,
        *,
        per_peer_timeout: float = 30,
        retry: bool = True,
    ) -> List[Dict]:
        """Collect state_root responses from all connected peers (parallel)."""
        height = self.blockchain.get_height()
        peers = list(self.peers.values())
        if not peers:
            return []

        async def _one(peer: PeerConnection) -> Optional[Dict]:
            if self.peers.get(peer.peer_id) is not peer:
                return None
            resp = await self.request_peer_state_root(
                peer,
                height,
                timeout=per_peer_timeout,
                retry=retry,
            )
            if resp:
                resp["peer_id"] = peer.peer_id
            return resp

        raw = await asyncio.gather(*(_one(p) for p in peers), return_exceptions=True)
        out: List[Dict] = []
        seen: set = set()
        for r in raw:
            if isinstance(r, Exception):
                self._peer_sync_fail += 1
                logger.warning("[P2P] state_root peer gather failed: %s", r)
                continue
            if isinstance(r, dict):
                pid = str(r.get("peer_id") or "")
                if pid:
                    seen.add(pid)
                out.append(r)
        if len(out) < len(peers):
            # Miner HOL: reply often lands after hub.clear() (5h STRICT:
            # solicit_timeouts≈late_accepts). Drain once more inside the
            # HTTP 8s STRICT budget (gate 1.2s + 6.5s wait + 0.4s grace + 0.4s).
            await asyncio.sleep(0.4)
            for peer in peers:
                pid = str(getattr(peer, "peer_id", "") or "")
                if not pid or pid in seen:
                    continue
                late = self._consume_late_state_root(peer)
                if late:
                    late["peer_id"] = pid
                    out.append(late)
        return out

    def request_peer_state_roots_sync(self, timeout: float = 15) -> Optional[List[Dict]]:
        if not self._loop or not self._running:
            return []
        if not self.peers:
            return []
        # Hard ceiling: callers (quick harness /health/ready) pass short timeouts.
        # Never inflate past the requested budget — that blocked HTTP handlers for
        # ~70s/peer and caused CI "harness: timed out" under a 60s urllib limit.
        budget = max(0.5, float(timeout))
        future = asyncio.run_coroutine_threadsafe(
            self._coalesced_peer_state_roots(),
            self._loop,
        )
        try:
            return future.result(timeout=budget)
        except TimeoutError as exc:
            # Do not cancel: HTTP waiters share one flight with sync_state.
            # Cancelling the 8s harness aborted the 70s background probe and
            # left _state_consistent sticky-false on an aligned mesh.
            logger.warning(
                "[P2P] state_root wire probe waiter timeout (inflight continues): %s",
                exc,
            )
            return None
        except Exception as exc:
            logger.warning("[P2P] state_root wire probe timeout/error: %s", exc)
            return None

    async def _request_block_by_hash(self, peer: PeerConnection, block_hash: str) -> Optional[Dict]:
        """Запрашивает у пира полный блок по hash."""
        if not block_hash:
            return None
        msg = await self._wait_peer_response(
            peer,
            (MSG_BLOCK,),
            timeout=15,
            presend=lambda: peer.send(MSG_GET_BLOCK_BY_HASH, {"hash": block_hash}),
            request_ctx={
                "kind": "block",
                "expected_hash": str(block_hash),
                "allow_null": True,
            },
        )
        if not msg or msg.get("type") != MSG_BLOCK:
            return None
        data = msg.get("data")
        return data if isinstance(data, dict) else None

    async def fetch_block_from_peers(self, block_hash: str) -> Optional[Dict]:
        """Ищет блок локально, затем у подключённых пиров."""
        if hasattr(self.blockchain, "get_block_by_hash"):
            local = self.blockchain.get_block_by_hash(block_hash)
            if local:
                return local
        for peer in list(self.peers.values()):
            blk = await self._request_block_by_hash(peer, block_hash)
            if blk and blk.get("hash") == block_hash:
                return blk
        return None

    def trigger_catch_up(self) -> None:
        """Schedule sync with all higher peers (callable from REST thread)."""
        if not self._loop or not self._running:
            return
        for peer in list(self.peers.values()):
            if peer.height > self.blockchain.get_height():
                asyncio.run_coroutine_threadsafe(self._sync_with_peer_safe(peer), self._loop)

    def catch_up_sync(self, timeout: float = 90) -> Dict:
        """Block until lagging peers are synced (REST / devnet scripts)."""
        if not self._loop or not self._running:
            return {"ok": False, "error": "p2p not running"}

        async def _run():
            deadline = time.monotonic() + max(5.0, float(timeout))
            last = {"ok": False, "height": self.blockchain.get_height(), "peer_height": 0}
            while time.monotonic() < deadline:
                our_h = self.blockchain.get_height()
                peer_max = max((p.height for p in self.peers.values()), default=our_h)
                if our_h >= peer_max:
                    return {
                        "ok": True,
                        "height": our_h,
                        "peer_height": peer_max,
                        "action": "synced",
                    }
                tasks = [
                    self._sync_with_peer_safe(peer)
                    for peer in list(self.peers.values())
                    if peer.height > our_h
                ]
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    self._record_broadcast_results(results, kind="catch_up_sync")
                new_h = self.blockchain.get_height()
                peer_max = max((p.height for p in self.peers.values()), default=new_h)
                last = {"ok": new_h >= peer_max, "height": new_h, "peer_height": peer_max}
                if last["ok"]:
                    return last
                await asyncio.sleep(2)
            return last

        try:
            return asyncio.run_coroutine_threadsafe(_run(), self._loop).result(timeout=timeout + 5)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "height": self.blockchain.get_height()}

    def reconcile_peers_sync(self, timeout: float = 90) -> Dict:
        """Block until peer reconcile completes (REST / devnet scripts)."""
        if not self._loop or not self._running:
            return {"ok": False, "error": "p2p not running"}
        try:
            return asyncio.run_coroutine_threadsafe(
                self.reconcile_peers(), self._loop
            ).result(timeout=timeout)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "height": self.blockchain.get_height()}

    def fetch_block_from_peers_sync(self, block_hash: str, timeout: float = 15) -> Optional[Dict]:
        """Синхронная обёртка для SyncEngine (из другого потока)."""
        if not self._loop or not self._running:
            return None
        future = asyncio.run_coroutine_threadsafe(
            self.fetch_block_from_peers(block_hash), self._loop
        )
        try:
            return future.result(timeout=timeout)
        except Exception as exc:
            self._peer_sync_fail += 1
            logger.warning(
                "[P2P] fetch_block_from_peers_sync failed hash=%s: %s",
                (block_hash or "")[:16],
                exc,
            )
            return None

    # ── Broadcast ────────────────────────────────────────────────────────────

    async def _broadcast_block(self, block_data: Dict, exclude_peer: str = ""):
        """Рассылает блок и актуальный status всем пирам (кроме exclude_peer)."""
        tasks = []
        block_h = int(block_data.get("height", block_data.get("number", 0)) or 0)
        block_hash = block_data.get("hash", "")
        status = {
            "height": block_h or self.blockchain.get_height(),
            "head_hash": block_hash or self.head() or "",
        }
        for pid, peer in list(self.peers.items()):
            if pid != exclude_peer:
                tasks.append(peer.send(MSG_NEW_BLOCK, block_data))
                tasks.append(peer.send(MSG_STATUS, status))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._record_broadcast_results(results, kind="block_broadcast")

    async def _handle_cross_shard_tx(self, peer: PeerConnection, data: Dict):
        parsed = native.validate_p2p_cross_shard_tx(data)
        if not parsed:
            self._strike_peer_sync(peer, "bad_cross_shard_tx")
            return
        if not self._sharding:
            return
        credited = False
        if hasattr(self._sharding, "receive_cross_shard_credit"):
            credited = bool(self._sharding.receive_cross_shard_credit(parsed))
        if credited:
            ack = {
                "tx_id": parsed.get("tx_id", ""),
                "shard_id": parsed.get("to_shard"),
                "to_shard": parsed.get("to_shard"),
                "status": "confirmed",
            }
            if self._sharding and hasattr(self._sharding, "validator_id"):
                vid = getattr(self._sharding, "validator_id", "") or getattr(
                    self._sharding, "node_id", ""
                )
                if vid:
                    ack["validator_id"] = vid
            await peer.send(MSG_CROSS_SHARD_ACK, ack)

    async def _handle_cross_shard_ack(self, peer: PeerConnection, data: Dict):
        parsed = native.validate_p2p_cross_shard_ack(data)
        if not parsed:
            self._strike_peer_sync(peer, "bad_cross_shard_ack")
            return
        if not self._sharding:
            return
        if hasattr(self._sharding, "receive_cross_shard_ack"):
            self._sharding.receive_cross_shard_ack(parsed)

    async def broadcast_cross_shard_ack(self, payload: Dict):
        if not isinstance(payload, dict):
            return
        tasks = [peer.send(MSG_CROSS_SHARD_ACK, payload) for peer in self.peers.values()]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._record_broadcast_results(results, kind="cross_shard_ack")

    async def broadcast_cross_shard_tx(self, payload: Dict):
        if not isinstance(payload, dict):
            return
        tasks = [peer.send(MSG_CROSS_SHARD_TX, payload) for peer in self.peers.values()]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._record_broadcast_results(results, kind="cross_shard_tx")

    async def _handle_shard_migration(self, peer: PeerConnection, data: Dict):
        parsed = native.validate_p2p_shard_migration(data)
        if not parsed:
            self._strike_peer_sync(peer, "bad_shard_migration")
            return
        if not self._sharding:
            return
        if hasattr(self._sharding, "receive_shard_migration"):
            self._sharding.receive_shard_migration(parsed)

    async def broadcast_shard_migration(self, payload: Dict):
        if not isinstance(payload, dict):
            return
        tasks = [peer.send(MSG_SHARD_MIGRATION, payload) for peer in self.peers.values()]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._record_broadcast_results(results, kind="shard_migration")

    async def broadcast_tx(self, tx_data: Dict):
        """Рассылает транзакцию всем пирам (full signed wire payload)."""
        from blockchain.mempool_wire import mempool_tx_to_wire

        tx_hash = tx_data.get("hash", tx_data.get("tx_hash", ""))
        if tx_hash and hasattr(self.mempool, "get_transaction"):
            mp_tx = self.mempool.get_transaction(tx_hash)
            if mp_tx:
                tx_data = mempool_tx_to_wire(mp_tx)
        if tx_hash:
            self._record_tx_propagation(
                tx_hash,
                "p2p_broadcast",
                detail={"peer_count": len(self.peers)},
            )
        tasks = [peer.send(MSG_NEW_TX, tx_data) for peer in self.peers.values()]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._record_broadcast_results(results, kind="tx_broadcast")

    # ── Колбэки EventBus ─────────────────────────────────────────────────────

    def _on_consensus_attestation(self, att_data: Dict):
        """Gossip signed attestation after local consensus.attest()."""
        if not self.validator_keys or not isinstance(att_data, dict):
            return
        validator = att_data.get("validator", "")
        block_hash = att_data.get("target_hash") or att_data.get("block_hash", "")
        if validator != self.validator_keys.get_address() or not block_hash:
            return
        blk = None
        if self.blockchain is not None and hasattr(self.blockchain, "get_block_by_hash"):
            try:
                blk = self.blockchain.get_block_by_hash(block_hash)
            except Exception as exc:
                logger.warning(
                    "[P2P] get_block_by_hash failed for attestation gossip: %s",
                    exc,
                )
                blk = None
        if not isinstance(blk, dict):
            # Do not gossip an attestation whose target header is unknown —
            # signing against live tip painted target_height≠header height.
            return
        number = blk.get("height", blk.get("number"))
        try:
            number = int(number)
        except (TypeError, ValueError):
            return
        block_data = {"hash": str(blk.get("hash") or block_hash), "number": number}
        slot = att_data.get("slot", 0)
        try:
            signed = self.validator_keys.sign_attestation(block_data, slot)
        except Exception as e:
            self._attestation_local_fail = int(self._attestation_local_fail or 0) + 1
            logger.warning("[P2P] Attestation sign failed: %s", e)
            return
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self._relay_attestation(signed), self._loop
            )

    def _on_local_block(self, block_data: Dict):
        """Вызывается EventBus при новом блоке — рассылаем пирам."""
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self._broadcast_block(block_data), self._loop
            )

    def _on_local_tx(self, tx_data: Dict):
        """Вызывается EventBus при новой транзакции — рассылаем пирам."""
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self.broadcast_tx(tx_data), self._loop
            )

    # ── Служебные задачи ─────────────────────────────────────────────────────

    async def _ping_loop(self):
        """Пинг всех пиров каждые 30 секунд, отключаем мёртвых."""
        while self._running:
            await asyncio.sleep(30)
            dead = []
            now = time.time()
            for pid, peer in list(self.peers.items()):
                if now - peer.last_seen > self.config.peer_timeout * 2:
                    dead.append(pid)
                else:
                    await peer.send(MSG_PING, {"ts": now})
            for pid in dead:
                self._remove_peer(pid)
            target_peers = max(1, int(getattr(self.config, "testnet_expected_peers", 1) or 1))
            if dead and len(self.peers) < target_peers:
                for addr in self._known_addrs:
                    parts = addr.rsplit(":", 1)
                    if len(parts) == 2:
                        try:
                            self._schedule_connect(parts[0], int(parts[1]))
                        except Exception as exc:
                            self._peer_connect_task_fail += 1
                            logger.warning(
                                "[P2P] reconnect task failed for %s: %s", addr, exc
                            )

    def _ingest_discovered_peers(self, peer: PeerConnection, data) -> int:
        """Remember + dial dialable addrs from a solicited MSG_PEERS payload."""
        peers = native.validate_p2p_peers_list(data)
        if peers is None:
            self._strike_peer_sync(peer, "bad_peers_list")
            return 0
        allow_private = bool(
            getattr(self.config, "p2p_discovery_allow_private", False)
        )
        ingested = 0
        for addr in peers[:10]:  # не больше 10 за раз
            if not native.p2p_peer_addr_is_dialable(
                addr, allow_private=allow_private
            ):
                self._discovery_dial_rejects_total = int(
                    self._discovery_dial_rejects_total or 0
                ) + 1
                continue
            parts = addr.rsplit(":", 1)
            if (
                self._use_libp2p_transport
                and len(parts) == 2
                and self._host_looks_like_libp2p_peer_id(parts[0])
            ):
                self._discovery_dial_rejects_total = int(
                    self._discovery_dial_rejects_total or 0
                ) + 1
                continue
            self._remember_addr(addr)
            parts = addr.rsplit(":", 1)
            if len(parts) == 2:
                try:
                    self._schedule_connect(parts[0], int(parts[1]))
                    ingested += 1
                except Exception as exc:
                    self._peer_connect_task_fail += 1
                    logger.warning(
                        "[P2P] connect_peer task failed for %s: %s", addr, exc
                    )
        return ingested

    async def _discovery_loop(self):
        """Периодически запрашиваем список пиров у уже подключённых."""
        while self._running:
            await asyncio.sleep(60)
            try:
                for peer in list(self.peers.values()):
                    # v1.3.152: solicit-armed get_peers — unsolicited MSG_PEERS refuse.
                    msg = await self._wait_peer_response(
                        peer,
                        (MSG_PEERS,),
                        timeout=12,
                        presend=lambda p=peer: p.send(MSG_GET_PEERS, {}),
                        request_ctx={"kind": "peers"},
                    )
                    if msg and msg.get("type") == MSG_PEERS:
                        self._ingest_discovered_peers(peer, msg.get("data"))
                # Переподключаемся к известным адресам если пиров мало
                target_peers = max(
                    1, int(getattr(self.config, "testnet_expected_peers", 1) or 1)
                )
                if len(self.peers) < target_peers:
                    for addr in self._known_addrs:
                        parts = addr.rsplit(":", 1)
                        if len(parts) == 2:
                            try:
                                self._schedule_connect(parts[0], int(parts[1]))
                            except Exception as exc:
                                self._peer_connect_task_fail += 1
                                logger.warning(
                                    "[P2P] discovery reconnect failed for %s: %s",
                                    addr,
                                    exc,
                                )
            except Exception as exc:
                self._discovery_loop_fail = int(self._discovery_loop_fail or 0) + 1
                logger.warning("[P2P] discovery_loop: %s", exc)

    async def _bootstrap_retry_loop(self):
        """v1.3.132: keep dialing missing bootstrap peers even if other peers exist.

        Stops sticky-first discovery eclipse: one random peer must not cancel bootstrap.
        """
        while self._running:
            await asyncio.sleep(20)
            try:
                if not self.config.bootstrap_peers:
                    continue
                missing = self._missing_bootstrap_addrs()
                if not missing:
                    continue
                for peer_addr in missing:
                    parts = str(peer_addr).rsplit(":", 1)
                    if len(parts) == 2:
                        try:
                            self._bootstrap_redial_total = int(
                                self._bootstrap_redial_total or 0
                            ) + 1
                            self._schedule_connect(parts[0], int(parts[1]))
                        except Exception as exc:
                            self._peer_connect_task_fail += 1
                            logger.warning(
                                "[P2P] bootstrap connect failed for %s: %s",
                                peer_addr,
                                exc,
                            )
            except Exception as exc:
                self._bootstrap_loop_fail = int(self._bootstrap_loop_fail or 0) + 1
                logger.warning("[P2P] bootstrap_retry_loop: %s", exc)

    @staticmethod
    def _normalize_dial_addr(addr: str) -> str:
        s = str(addr or "").strip()
        if not s or ":" not in s:
            return ""
        host, port_s = s.rsplit(":", 1)
        host = host.strip().strip("[]").lower()
        try:
            port = int(port_s)
        except (TypeError, ValueError):
            return ""
        if not host or port <= 0:
            return ""
        return f"{host}:{port}"

    def _bootstrap_pin_for_addr(self, addr: str) -> Optional[dict]:
        pins = bootstrap_pin_map(self.config)
        if not pins:
            return None
        want = self._normalize_dial_addr(addr)
        return pins.get(want) if want else None

    def _bootstrap_pin_for_peer(self, peer: PeerConnection) -> Optional[dict]:
        """Resolve pin for a peer via dial_target or host:listen_port."""
        pins = bootstrap_pin_map(self.config)
        if not pins:
            return None
        candidates = []
        dial = self._normalize_dial_addr(str(getattr(peer, "dial_target", "") or ""))
        if dial:
            candidates.append(dial)
        host = str(peer.host or "").strip().strip("[]")
        port = int(peer.listen_port or peer.port or 0)
        if host and port > 0:
            candidates.append(self._normalize_dial_addr(f"{host}:{port}"))
        for c in candidates:
            if c and c in pins:
                return pins[c]
        return None

    def _bootstrap_pin_reject_reason(
        self, peer: PeerConnection, claimed_id: str, fingerprint: str
    ) -> str:
        """Empty if OK / no pin; else strike reason for pin mismatch."""
        pin = self._bootstrap_pin_for_peer(peer)
        if not pin:
            return ""
        want_fp = str(pin.get("fingerprint") or "").strip().lower()
        got_fp = str(fingerprint or "").strip().lower().replace(":", "")
        if want_fp and got_fp != want_fp:
            return "bootstrap_pin_mismatch"
        want_id = str(pin.get("node_id") or "").strip()
        if want_id and str(claimed_id or "").strip() != want_id:
            return "bootstrap_pin_node_id_mismatch"
        if want_fp and not got_fp:
            return "bootstrap_pin_missing_tls"
        return ""

    def _bind_bootstrap_peer(self, addr: str, peer_id: str) -> None:
        """Remember that boot_addr is satisfied by peer_id (stops IP≠hostname redials)."""
        want = self._normalize_dial_addr(addr)
        pid = str(peer_id or "").strip()
        if not want or not pid:
            return
        ids = getattr(self, "_bootstrap_peer_ids", None)
        if ids is None:
            self._bootstrap_peer_ids = {}
            ids = self._bootstrap_peer_ids
        ids[want] = pid

    def _bootstrap_already_covered(self, host: str, port: int) -> bool:
        want = self._normalize_dial_addr(f"{host}:{int(port)}")
        if not want:
            return False
        pid = str((getattr(self, "_bootstrap_peer_ids", {}) or {}).get(want) or "")
        return bool(pid and pid in self.peers)

    def _peer_covers_bootstrap(self, peer: PeerConnection, boot_addr: str) -> bool:
        """True if this live peer satisfies a configured bootstrap target."""
        want = self._normalize_dial_addr(boot_addr)
        if not want:
            return False
        pid = str(getattr(peer, "peer_id", "") or "").strip()
        bound = str((getattr(self, "_bootstrap_peer_ids", {}) or {}).get(want) or "")
        if bound and pid and bound == pid:
            return True
        # Pin node_id alone can cover when peer connected via docker bridge IP.
        pin = self._bootstrap_pin_for_addr(want)
        if pin:
            want_id = str(pin.get("node_id") or "").strip()
            if want_id and pid and want_id == pid:
                want_fp = str(pin.get("fingerprint") or "").strip().lower()
                got_fp = (
                    str(getattr(peer, "tls_fingerprint", "") or "")
                    .strip()
                    .lower()
                    .replace(":", "")
                )
                if want_fp and got_fp and got_fp != want_fp:
                    return False
                if want_fp and not got_fp:
                    return False
                return True
        dial = self._normalize_dial_addr(str(getattr(peer, "dial_target", "") or ""))
        addr_ok = bool(dial and dial == want)
        if not addr_ok:
            host, _, port_s = want.partition(":")
            try:
                port = int(port_s)
            except (TypeError, ValueError):
                return False
            ph = str(peer.host or "").strip().strip("[]").lower()
            pl = int(peer.listen_port or peer.port or 0)
            addr_ok = bool(ph and ph == host and pl == port)
        if not addr_ok:
            return False
        # v1.3.133: when a pin is configured, fingerprint[/node_id] must match.
        if not pin:
            pin = self._bootstrap_pin_for_addr(want)
        if not pin:
            if pid:
                self._bind_bootstrap_peer(want, pid)
            return True
        want_fp = str(pin.get("fingerprint") or "").strip().lower()
        got_fp = str(getattr(peer, "tls_fingerprint", "") or "").strip().lower().replace(
            ":", ""
        )
        if want_fp and got_fp != want_fp:
            return False
        want_id = str(pin.get("node_id") or "").strip()
        if want_id and pid != want_id:
            return False
        if pid:
            self._bind_bootstrap_peer(want, pid)
        return True

    def _missing_bootstrap_addrs(self) -> list:
        """Bootstrap addresses not covered by any connected peer."""
        out = []
        peers = list(self.peers.values())
        for raw in list(getattr(self.config, "bootstrap_peers", []) or []):
            addr = str(raw).strip()
            if not self._normalize_dial_addr(addr):
                continue
            if any(self._peer_covers_bootstrap(p, addr) for p in peers):
                continue
            out.append(addr)
        return out

    async def _maintenance_loop(self):
        """Periodic peer hygiene: stale eviction, ban expiry, low-score drops."""
        interval = max(
            15.0,
            float(getattr(self.config, "peer_timeout", 30) or 30),
        )
        while self._running:
            await asyncio.sleep(interval)
            try:
                removed = self._prune_stale_peers()
                if removed:
                    logger.info("[P2P] maintenance pruned %s peer(s)", removed)
                active_keys = {self._peer_key(p) for p in self.peers.values()}
                if self._rl_table is not None:
                    with self._rl_lock:
                        self._rl_table.retain_strike_keys(list(active_keys))
                for key in list(self._peer_strikes):
                    if key not in active_keys:
                        self._peer_strikes.pop(key, None)
            except Exception as exc:
                self._maintenance_loop_fail = int(self._maintenance_loop_fail or 0) + 1
                logger.warning("[P2P] maintenance_loop: %s", exc)

    async def _catch_up_loop(self):
        """Периодически догоняем пиров с большей высотой."""
        while self._running:
            await asyncio.sleep(5)
            try:
                our_height = int(self.blockchain.get_height() or 0)
                our_status = {
                    "height": our_height,
                    "head_hash": self.head() or "",
                }
                for peer in list(self.peers.values()):
                    ok_send = await peer.send(MSG_STATUS, our_status)
                    if not ok_send:
                        self._peer_status_send_fail = int(
                            self._peer_status_send_fail or 0
                        ) + 1
                        continue
                    if peer.height > our_height:
                        self._schedule_sync(peer)
                target_peers = max(1, int(getattr(self.config, "testnet_expected_peers", 1) or 1))
                if len(self.peers) < target_peers:
                    for addr in list(self._known_addrs):
                        parts = addr.rsplit(":", 1)
                        if len(parts) == 2:
                            try:
                                self._schedule_connect(parts[0], int(parts[1]))
                            except Exception as exc:
                                self._peer_connect_task_fail += 1
                                logger.warning(
                                    "[P2P] catch-up connect task failed for %s: %s",
                                    addr,
                                    exc,
                                )
            except Exception as exc:
                self._catch_up_loop_fail = int(self._catch_up_loop_fail or 0) + 1
                logger.warning("[P2P] catch_up_loop: %s", exc)

    async def _solo_node_hint(self):
        """One-time hint when running without peers (normal for solo dev)."""
        await asyncio.sleep(45)
        if not self._running or self.peers:
            return
        if self.config.bootstrap_peers:
            print("[P2P] No peers connected — check BOOTSTRAP_PEERS / firewall")
        else:
            print(
                "[P2P] Solo mode (0 peers). For a second node: "
                f"python main.py --port 5001 --peers 127.0.0.1:{self.config.p2p_port}"
            )

    def _refresh_eclipse_snapshot(self) -> Dict:
        """Update eclipse telemetry from live peer IPs (v1.3.89)."""
        snap = self.peer_manager.refresh_eclipse_snapshot()
        self._eclipse_public_peers = int(self.peer_manager.eclipse.public_peers or 0)
        self._eclipse_unique_public_subnets = int(
            self.peer_manager.eclipse.unique_public_subnets or 0
        )
        self._eclipse_ratio = float(self.peer_manager.eclipse.eclipse_ratio or 0)
        self._eclipse_at_risk = 1 if self.peer_manager.eclipse.at_risk else 0
        return snap

    def _maybe_eclipse_prune(self, *, local_height: int, health_timeout: float) -> int:
        """If public peers are eclipse-at-risk, drop lowest-score peer in densest subnet."""
        n = self.peer_manager.maybe_eclipse_prune(
            local_height=local_height,
            health_timeout=health_timeout,
        )
        self._eclipse_prune_total = int(self.peer_manager.eclipse.prune_total or 0)
        return n

    def _remove_peer(self, peer_id: str, expected: Optional[PeerConnection] = None):
        peer = self.peer_manager.unregister(peer_id, expected, close=True)
        if peer is not None:
            lp = str(getattr(peer, "_libp2p_peer_id", "") or "")
            if lp and self._libp2p_sessions.get(lp) is peer:
                self._libp2p_sessions.pop(lp, None)
            print(f"[P2P] Disconnected: {peer_id[:12]}")

    # ── Статистика ───────────────────────────────────────────────────────────

    def get_peers_info(self) -> List[Dict]:
        return self.peer_manager.peers_info()

    def peer_count(self) -> int:
        return self.peer_manager.peer_count()

    def get_stats(self) -> Dict:
        stats = {
            "peers": self.peer_count(),
            "known_addresses": len(self._known_addrs),
            "running": self._running,
            "port": self.config.p2p_port,
            "sync_engine": self.sync_engine is not None,
            "state_consistent": self._state_consistent,
            "state_root": self.blockchain.get_state_root() if self.blockchain else "",
        }
        if self.sync_engine:
            stats["sync_status"] = self.sync_engine.get_status()
        return stats

    def get_topology(self) -> Dict:
        """Operational P2P topology for real multi-node devnet diagnostics."""
        local_height = self.blockchain.get_height() if self.blockchain else 0
        local_head = self.head() or ""
        peers = []
        now = time.time()
        health_timeout = max(
            30.0,
            float(getattr(self.config, "peer_timeout", 30) or 30) * 2,
        )
        for p in self.peers.values():
            gap = abs(int(p.height or 0) - int(local_height or 0))
            last_seen_age = max(0.0, now - p.last_seen)
            score = self._score_peer(
                p,
                local_height=int(local_height or 0),
                health_timeout=health_timeout,
                now=now,
            )
            strikes = self._peer_strike_count(p)
            peer_head = str(p.head or "")
            transport_healthy = gap <= 2 and last_seen_age < health_timeout
            # Same-height divergent head is not chain-compatible.
            chain_compatible = True
            if peer_head and local_head and gap == 0:
                chain_compatible = peer_head == local_head
            peers.append({
                "peer_id": p.peer_id,
                "address": f"{p.host}:{p.listen_port or p.port}",
                "socket_address": f"{p.host}:{p.port}",
                "listen_port": p.listen_port,
                "height": p.height,
                "height_gap": gap,
                "head": peer_head,
                "connected_for_sec": int(now - p.connected_at),
                "last_seen_age_sec": round(last_seen_age, 3),
                "health_timeout_sec": int(health_timeout),
                "transport_healthy": transport_healthy,
                "chain_compatible": chain_compatible,
                "healthy": transport_healthy and chain_compatible,
                "score": score,
                "strikes": strikes,
                "import_fails": int(getattr(p, "quality_import_fails", 0) or 0),
                "banned": self._is_banned(self._peer_key(p)),
            })
        expected = int(getattr(self.config, "testnet_expected_peers", 0) or 0)
        mode = str(getattr(self.config, "deployment_mode", "dev") or "dev").lower()
        mesh_min = int(getattr(self.config, "mesh_min_peers_before_mine", 0) or 0)
        # Prod/staging: zero peers must not report topology_healthy when mesh is expected.
        if expected <= 0 and mode in ("prod", "production", "staging"):
            expected = max(1, mesh_min)
        scores = [p["score"] for p in peers]
        peer_links_ok = (len(peers) >= expected) if expected else True
        peers_healthy = all(p["healthy"] for p in peers) if peers else True
        # With live peers, topology must not greenwash without state consistency.
        consistent_ok = bool(self._state_consistent) if peers else True
        return {
            "node_id": getattr(self.config, "node_id", ""),
            "chain_id": getattr(self.config, "chain_id", 0),
            "running": self._running,
            "local_height": local_height,
            "local_head": local_head,
            "peer_count": len(peers),
            "expected_peers": expected,
            "topology_healthy": peer_links_ok and peers_healthy and consistent_ok,
            "bootstrap_peers": list(getattr(self.config, "bootstrap_peers", []) or []),
            "known_addresses": list(self._known_addrs),
            "peers": peers,
            "state_consistent": self._state_consistent,
            "peer_score_min": min(scores) if scores else None,
            "peer_score_avg": round(sum(scores) / len(scores), 2) if scores else None,
            "security": self.get_p2p_security_status(),
        }

    def get_p2p_security_status(self) -> Dict:
        self._refresh_eclipse_snapshot()
        now = time.time()
        bw_rejects = 0
        eg_rejects = int(self._egress_rejects or 0)
        if self._rl_table is not None:
            def _security_bans():
                active_bans = []
                for key in self._rl_table.ban_keys():
                    until = self._rl_table.ban_until(key)
                    if until is None or until <= now:
                        continue
                    if not self._rl_table.is_banned(key, float(now)):
                        continue
                    active_bans.append(
                        {
                            "key": key,
                            "seconds_remaining": max(0, int(until - now)),
                        }
                    )
                tracked = int(self._rl_table.tracked_strikes())
                bw = int(getattr(self._rl_table, "bandwidth_rejects", 0) or 0)
                eg = int(getattr(self._rl_table, "egress_rejects", 0) or 0)
                return active_bans, tracked, bw, eg

            with self._rl_lock:
                active_bans, tracked, bw_rejects, eg_rejects = _security_bans()
        else:
            active_bans = [
                {
                    "key": key,
                    "seconds_remaining": max(0, int(until - now)),
                }
                for key, until in self._peer_bans.items()
                if until > now
            ]
            tracked = len(self._peer_strikes)
        status = {
            "rate_limit_per_sec": int(getattr(self.config, "p2p_max_messages_per_sec", 0) or 0),
            "max_message_bytes": _max_p2p_line_bytes(self.config),
            "ban_seconds": int(getattr(self.config, "p2p_ban_seconds", 300) or 300),
            "strikes_before_ban": int(getattr(self.config, "p2p_rate_limit_strikes", 5) or 5),
            "evict_min_score": int(getattr(self.config, "p2p_evict_min_score", 0) or 0),
            "active_bans": len(active_bans),
            "banned": active_bans[:20],
            "tracked_strikes": tracked,
            "native_rate_limit_table": self._rl_table is not None,
            "native_p2p_ingress": bool(self._use_native_ingress and self._rl_table is not None),
            "native_p2p_egress": bool(self._use_native_egress and self._rl_table is not None),
            "native_p2p_egress_prepare": bool(
                self._use_native_egress and hasattr(native, "p2p_egress_prepare")
            ),
            "native_p2p_framer": bool(hasattr(native, "P2PLineFramer")),
            "native_conn_governor": self._conn_governor is not None,
            "native_p2p_transport": bool(self._use_native_transport),
            "native_p2p_tls": bool(getattr(self, "_native_tls", False)),
            "native_read_message": bool(getattr(self, "_native_read_message", False)),
            "native_write_message": bool(getattr(self, "_native_write_message", False)),
            "native_read_messages": bool(getattr(self, "_native_read_messages", False)),
            "native_write_messages": bool(getattr(self, "_native_write_messages", False)),
            "native_handshake": bool(getattr(self, "_native_handshake", False)),
            "native_peer_identities": bool(getattr(self, "_native_peer_identities", False)),
            "native_mid_session_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_auto_pong": bool(getattr(self, "_native_auto_pong", False)),
            "native_keepalive": bool(getattr(self, "_native_auto_pong", False)),
            "native_housekeeping_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_status_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_attestation_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_block_sync_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_block_fetch_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_tx_gossip_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_block_payload_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_peer_discovery_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_state_root_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_cross_shard_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_handshake_payload_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_handshake_policy_gate": bool(getattr(self, "_use_native_transport", False)),
            "native_message_loop_shell": bool(
                getattr(self, "_native_message_loop_shell", False)
            ),
            "native_attestation_semantic_gate": bool(
                getattr(self, "_native_message_loop_shell", False)
            ),
            "native_tx_semantic_gate": bool(
                getattr(self, "_native_message_loop_shell", False)
            ),
            "native_mempool_semantic_gate": bool(
                getattr(self, "_native_message_loop_shell", False)
            ),
            "native_block_semantic_gate": bool(
                getattr(self, "_native_message_loop_shell", False)
            ),
            "native_blocks_batch_semantic_gate": bool(
                getattr(self, "_native_message_loop_shell", False)
            ),
            "native_block_payload_semantic_gate": bool(
                getattr(self, "_native_message_loop_shell", False)
            ),
            "native_state_root_response_semantic_gate": bool(
                getattr(self, "_native_message_loop_shell", False)
            ),
            "native_status_head_hash_semantic_gate": bool(
                getattr(self, "_native_message_loop_shell", False)
            ),
            "native_blocks_response_semantic_gate": True,
            "native_block_response_semantic_gate": True,
            "native_state_root_response_request_gate": True,
            "native_state_root_outbound_honesty": True,
            "native_state_root_response_head_gate": True,
            "native_state_root_local_consistency": True,
            "native_mempool_solicit_only": True,
            "native_mempool_solicit_armed_shell": True,
            "native_peer_score_quality": True,
            "native_new_block_height_cap": True,
            "native_height_cap_clear_head": bool(
                getattr(self.config, "p2p_height_cap_clear_head", True)
            ),
            "native_new_block_head_height_bind": bool(
                getattr(self.config, "p2p_new_block_head_height_bind", True)
            ),
            "native_new_block_announce_body_bind": bool(
                getattr(self.config, "p2p_new_block_announce_body_bind", True)
            ),
            "native_new_block_contiguous_parent_bind": bool(
                getattr(self.config, "p2p_new_block_contiguous_parent_bind", True)
            ),
            "native_new_block_same_height_parent_bind": bool(
                getattr(self.config, "p2p_new_block_same_height_parent_bind", True)
            ),
            "native_new_block_tip_head_bind": bool(
                getattr(self.config, "p2p_new_block_tip_head_bind", True)
            ),
            "native_new_block_defer_tip": True,
            "native_status_head_height_bind": bool(
                getattr(self.config, "p2p_status_head_height_bind", True)
            ),
            "native_status_head_requires_height": bool(
                getattr(self.config, "p2p_status_head_requires_height", True)
            ),
            "native_handshake_head_requires_height": bool(
                getattr(self.config, "p2p_handshake_head_requires_height", True)
            ),
            "native_handshake_height_cap": True,
            "native_status_capped_head_refuse": True,
            "native_attestation_slot_ahead": True,
            "native_attestation_local_head": True,
            "native_attestation_target_head_bind": bool(
                getattr(self.config, "p2p_attestation_target_head_bind", True)
            ),
            "native_block_solicit_only": True,
            "native_state_root_solicit_only": True,
            "native_peers_solicit_only": bool(
                getattr(self.config, "p2p_peers_solicit_only", True)
            ),
            "native_catch_up_require_head": bool(
                getattr(self.config, "p2p_catch_up_require_head", True)
            ),
            "native_catch_up_tip_probe": bool(
                getattr(self.config, "p2p_catch_up_tip_probe", True)
            ),
            "native_catch_up_peer_head_probe": bool(
                getattr(self.config, "p2p_catch_up_peer_head_probe", True)
            ),
            "native_catch_up_peer_head_parent_bind": bool(
                getattr(self.config, "p2p_catch_up_peer_head_parent_bind", True)
            ),
            "native_catch_up_tip_head_bind": bool(
                getattr(self.config, "p2p_catch_up_tip_head_bind", True)
            ),
            "native_catch_up_contiguous_parent_bind": bool(
                getattr(self.config, "p2p_catch_up_contiguous_parent_bind", True)
            ),
            "native_catch_up_height_continuity_bind": bool(
                getattr(
                    self.config, "p2p_catch_up_height_continuity_bind", True
                )
            ),
            "native_fork_peer_head_probe": bool(
                getattr(self.config, "p2p_fork_peer_head_probe", True)
            ),
            "native_fork_peer_head_parent_bind": bool(
                getattr(self.config, "p2p_fork_peer_head_parent_bind", True)
            ),
            "native_reconcile_head_hash_bind": bool(
                getattr(self.config, "p2p_reconcile_head_hash_bind", True)
            ),
            "native_ghost_head_probe": bool(
                getattr(self.config, "p2p_ghost_head_probe", True)
            ),
            "native_ghost_head_parent_bind": bool(
                getattr(self.config, "p2p_ghost_head_parent_bind", True)
            ),
            "native_reconcile_contiguous_parent_bind": bool(
                getattr(self.config, "p2p_reconcile_contiguous_parent_bind", True)
            ),
            "native_reconcile_same_height_parent_bind": bool(
                getattr(self.config, "p2p_reconcile_same_height_parent_bind", True)
            ),
            "native_reconcile_tip_head_bind": bool(
                getattr(self.config, "p2p_reconcile_tip_head_bind", True)
            ),
            "native_catch_up_head_height_bind": True,
            "native_sync_heads_no_invent": True,
            "native_sync_state_wire_only": True,
            "native_mempool_new_tx_rate_primary": True,
            "native_mempool_cheap_refuse": True,
            "native_mempool_min_fee_refuse": bool(
                getattr(self.config, "p2p_mempool_min_fee_refuse", True)
            ),
            "native_mempool_max_fee_refuse": bool(
                getattr(self.config, "p2p_mempool_max_fee_refuse", True)
            ),
            "native_mempool_max_gas_refuse": bool(
                getattr(self.config, "p2p_mempool_max_gas_refuse", True)
            ),
            "native_mempool_max_calldata_refuse": bool(
                getattr(self.config, "p2p_mempool_max_calldata_refuse", True)
            ),
            "native_mempool_negative_value_refuse": bool(
                getattr(self.config, "p2p_mempool_negative_value_refuse", True)
            ),
            "native_mempool_max_value_refuse": bool(
                getattr(self.config, "p2p_mempool_max_value_refuse", True)
            ),
            "native_mempool_negative_nonce_refuse": bool(
                getattr(self.config, "p2p_mempool_negative_nonce_refuse", True)
            ),
            "native_mempool_max_nonce_refuse": bool(
                getattr(self.config, "p2p_mempool_max_nonce_refuse", True)
            ),
            "native_mempool_negative_fee_refuse": bool(
                getattr(self.config, "p2p_mempool_negative_fee_refuse", True)
            ),
            "native_mempool_negative_gas_refuse": bool(
                getattr(self.config, "p2p_mempool_negative_gas_refuse", True)
            ),
            "native_mempool_unparseable_gas_refuse": bool(
                getattr(self.config, "p2p_mempool_unparseable_gas_refuse", True)
            ),
            "native_mempool_unparseable_value_refuse": bool(
                getattr(self.config, "p2p_mempool_unparseable_value_refuse", True)
            ),
            "native_mempool_unparseable_nonce_refuse": bool(
                getattr(self.config, "p2p_mempool_unparseable_nonce_refuse", True)
            ),
            "native_mempool_empty_from_refuse": bool(
                getattr(self.config, "p2p_mempool_empty_from_refuse", True)
            ),
            "native_mempool_max_from_refuse": bool(
                getattr(self.config, "p2p_mempool_max_from_refuse", True)
            ),
            "native_mempool_empty_to_refuse": bool(
                getattr(self.config, "p2p_mempool_empty_to_refuse", True)
            ),
            "native_mempool_max_to_refuse": bool(
                getattr(self.config, "p2p_mempool_max_to_refuse", True)
            ),
            "native_mempool_empty_hash_refuse": bool(
                getattr(self.config, "p2p_mempool_empty_hash_refuse", True)
            ),
            "native_mempool_max_hash_refuse": bool(
                getattr(self.config, "p2p_mempool_max_hash_refuse", True)
            ),
            "native_mempool_empty_sig_refuse": bool(
                getattr(self.config, "p2p_mempool_empty_sig_refuse", True)
            ),
            "native_mempool_empty_pubkey_refuse": bool(
                getattr(self.config, "p2p_mempool_empty_pubkey_refuse", True)
            ),
            "native_mempool_max_sig_refuse": bool(
                getattr(self.config, "p2p_mempool_max_sig_refuse", True)
            ),
            "native_mempool_max_pubkey_refuse": bool(
                getattr(self.config, "p2p_mempool_max_pubkey_refuse", True)
            ),
            "native_mempool_nonfinite_value_refuse": bool(
                getattr(self.config, "p2p_mempool_nonfinite_value_refuse", True)
            ),
            "native_mempool_nonfinite_fee_refuse": bool(
                getattr(self.config, "p2p_mempool_nonfinite_fee_refuse", True)
            ),
            "native_get_blocks_future_refuse": bool(
                getattr(self.config, "p2p_get_blocks_future_refuse", True)
            ),
            "native_get_block_future_refuse": bool(
                getattr(self.config, "p2p_get_block_future_refuse", True)
            ),
            "native_get_blocks_past_tip_clamp": bool(
                getattr(self.config, "p2p_get_blocks_past_tip_clamp", True)
            ),
            "native_mempool_serve_tip_align": bool(
                getattr(self.config, "p2p_mempool_serve_tip_align", True)
            ),
            "native_tx_sig_before_state": True,
            "native_bootstrap_resilient": True,
            "native_bootstrap_pin_gate": True,
            "native_discovery_dialability_gate": True,
            "native_handshake_head_semantic_gate": True,
            "native_status_height_head_gate": True,
            "attestation_semantic_rejects_total": int(
                getattr(self, "_attestation_semantic_rejects_total", 0) or 0
            ),
            "tx_semantic_rejects_total": int(
                getattr(self, "_tx_semantic_rejects_total", 0) or 0
            ),
            "block_semantic_rejects_total": int(
                getattr(self, "_block_semantic_rejects_total", 0) or 0
            ),
            "state_root_semantic_rejects_total": int(
                getattr(self, "_state_root_semantic_rejects_total", 0) or 0
            ),
            "status_semantic_rejects_total": int(
                getattr(self, "_status_semantic_rejects_total", 0) or 0
            ),
            "blocks_response_semantic_rejects_total": int(
                getattr(self, "_blocks_response_semantic_rejects_total", 0) or 0
            ),
            "block_response_semantic_rejects_total": int(
                getattr(self, "_block_response_semantic_rejects_total", 0) or 0
            ),
            "state_root_response_request_rejects_total": int(
                getattr(self, "_state_root_response_request_rejects_total", 0) or 0
            ),
            "state_root_outbound_refuse_total": int(
                getattr(self, "_state_root_outbound_refuse_total", 0) or 0
            ),
            "state_root_late_accepts_total": int(
                getattr(self, "_state_root_late_accepts_total", 0) or 0
            ),
            "discovery_dial_rejects_total": int(
                getattr(self, "_discovery_dial_rejects_total", 0) or 0
            ),
            "handshake_head_rejects_total": int(
                getattr(self, "_handshake_head_rejects_total", 0) or 0
            ),
            "status_height_head_rejects_total": int(
                getattr(self, "_status_height_head_rejects_total", 0) or 0
            ),
            "unsolicited_mempool_rejects_total": int(
                getattr(self, "_unsolicited_mempool_rejects_total", 0) or 0
            ),
            "soft_refuse_total": int(getattr(self, "_soft_refuse_total", 0) or 0),
            "status_height_cap_total": int(
                getattr(self, "_status_height_cap_total", 0) or 0
            ),
            "new_block_height_cap_total": int(
                getattr(self, "_new_block_height_cap_total", 0) or 0
            ),
            "new_block_head_height_mismatch_total": int(
                getattr(self, "_new_block_head_height_mismatch_total", 0) or 0
            ),
            "new_block_announce_body_refuse_total": int(
                getattr(self, "_new_block_announce_body_refuse_total", 0) or 0
            ),
            "new_block_contiguous_parent_mismatch_total": int(
                getattr(self, "_new_block_contiguous_parent_mismatch_total", 0) or 0
            ),
            "new_block_same_height_parent_mismatch_total": int(
                getattr(
                    self, "_new_block_same_height_parent_mismatch_total", 0
                )
                or 0
            ),
            "new_block_tip_head_mismatch_total": int(
                getattr(self, "_new_block_tip_head_mismatch_total", 0) or 0
            ),
            "status_head_height_mismatch_total": int(
                getattr(self, "_status_head_height_mismatch_total", 0) or 0
            ),
            "status_head_without_height_total": int(
                getattr(self, "_status_head_without_height_total", 0) or 0
            ),
            "handshake_head_without_height_total": int(
                getattr(self, "_handshake_head_without_height_total", 0) or 0
            ),
            "handshake_height_cap_total": int(
                getattr(self, "_handshake_height_cap_total", 0) or 0
            ),
            "state_root_local_rejects_total": int(
                getattr(self, "_state_root_local_rejects_total", 0) or 0
            ),
            "attestation_slot_ahead_rejects_total": int(
                getattr(self, "_attestation_slot_ahead_rejects_total", 0) or 0
            ),
            "attestation_local_head_rejects_total": int(
                getattr(self, "_attestation_local_head_rejects_total", 0) or 0
            ),
            "attestation_echo_drops_total": int(
                getattr(self, "_attestation_echo_drops_total", 0) or 0
            ),
            "attestation_dup_drops_total": int(
                getattr(self, "_attestation_dup_drops_total", 0) or 0
            ),
            "attestation_target_head_rejects_total": int(
                getattr(self, "_attestation_target_head_rejects_total", 0) or 0
            ),
            "unsolicited_block_rejects_total": int(
                getattr(self, "_unsolicited_block_rejects_total", 0) or 0
            ),
            "unsolicited_state_root_rejects_total": int(
                getattr(self, "_unsolicited_state_root_rejects_total", 0) or 0
            ),
            "unsolicited_peers_rejects_total": int(
                getattr(self, "_unsolicited_peers_rejects_total", 0) or 0
            ),
            "catch_up_no_head_refuse_total": int(
                getattr(self, "_catch_up_no_head_refuse_total", 0) or 0
            ),
            "catch_up_head_height_mismatch_total": int(
                getattr(self, "_catch_up_head_height_mismatch_total", 0) or 0
            ),
            "catch_up_tip_probe_refuse_total": int(
                getattr(self, "_catch_up_tip_probe_refuse_total", 0) or 0
            ),
            "catch_up_peer_head_probe_refuse_total": int(
                getattr(self, "_catch_up_peer_head_probe_refuse_total", 0) or 0
            ),
            "catch_up_tip_head_mismatch_total": int(
                getattr(self, "_catch_up_tip_head_mismatch_total", 0) or 0
            ),
            "catch_up_contiguous_parent_mismatch_total": int(
                getattr(
                    self, "_catch_up_contiguous_parent_mismatch_total", 0
                )
                or 0
            ),
            "catch_up_height_continuity_mismatch_total": int(
                getattr(
                    self, "_catch_up_height_continuity_mismatch_total", 0
                )
                or 0
            ),
            "fork_peer_head_probe_refuse_total": int(
                getattr(self, "_fork_peer_head_probe_refuse_total", 0) or 0
            ),
            "reconcile_head_hash_mismatch_total": int(
                getattr(self, "_reconcile_head_hash_mismatch_total", 0) or 0
            ),
            "ghost_head_probe_refuse_total": int(
                getattr(self, "_ghost_head_probe_refuse_total", 0) or 0
            ),
            "reconcile_contiguous_parent_mismatch_total": int(
                getattr(self, "_reconcile_contiguous_parent_mismatch_total", 0) or 0
            ),
            "reconcile_same_height_parent_mismatch_total": int(
                getattr(
                    self, "_reconcile_same_height_parent_mismatch_total", 0
                )
                or 0
            ),
            "reconcile_tip_head_mismatch_total": int(
                getattr(self, "_reconcile_tip_head_mismatch_total", 0) or 0
            ),
            "heads_skipped_no_head": int(
                getattr(getattr(self, "sync_engine", None), "_heads_skipped_no_head", 0)
                or 0
            ),
            "mempool_dup_refuse_total": int(
                getattr(self, "_mempool_dup_refuse_total", 0) or 0
            ),
            "mempool_fee_refuse_total": int(
                getattr(self, "_mempool_fee_refuse_total", 0) or 0
            ),
            "mempool_fee_high_refuse_total": int(
                getattr(self, "_mempool_fee_high_refuse_total", 0) or 0
            ),
            "mempool_gas_refuse_total": int(
                getattr(self, "_mempool_gas_refuse_total", 0) or 0
            ),
            "mempool_calldata_refuse_total": int(
                getattr(self, "_mempool_calldata_refuse_total", 0) or 0
            ),
            "mempool_value_refuse_total": int(
                getattr(self, "_mempool_value_refuse_total", 0) or 0
            ),
            "mempool_value_high_refuse_total": int(
                getattr(self, "_mempool_value_high_refuse_total", 0) or 0
            ),
            "mempool_nonce_refuse_total": int(
                getattr(self, "_mempool_nonce_refuse_total", 0) or 0
            ),
            "mempool_nonce_high_refuse_total": int(
                getattr(self, "_mempool_nonce_high_refuse_total", 0) or 0
            ),
            "mempool_fee_negative_refuse_total": int(
                getattr(self, "_mempool_fee_negative_refuse_total", 0) or 0
            ),
            "mempool_gas_negative_refuse_total": int(
                getattr(self, "_mempool_gas_negative_refuse_total", 0) or 0
            ),
            "mempool_gas_unparseable_refuse_total": int(
                getattr(self, "_mempool_gas_unparseable_refuse_total", 0) or 0
            ),
            "mempool_value_unparseable_refuse_total": int(
                getattr(self, "_mempool_value_unparseable_refuse_total", 0) or 0
            ),
            "mempool_nonce_unparseable_refuse_total": int(
                getattr(self, "_mempool_nonce_unparseable_refuse_total", 0) or 0
            ),
            "mempool_empty_from_refuse_total": int(
                getattr(self, "_mempool_empty_from_refuse_total", 0) or 0
            ),
            "mempool_from_size_refuse_total": int(
                getattr(self, "_mempool_from_size_refuse_total", 0) or 0
            ),
            "mempool_empty_to_refuse_total": int(
                getattr(self, "_mempool_empty_to_refuse_total", 0) or 0
            ),
            "mempool_to_size_refuse_total": int(
                getattr(self, "_mempool_to_size_refuse_total", 0) or 0
            ),
            "mempool_empty_hash_refuse_total": int(
                getattr(self, "_mempool_empty_hash_refuse_total", 0) or 0
            ),
            "mempool_hash_size_refuse_total": int(
                getattr(self, "_mempool_hash_size_refuse_total", 0) or 0
            ),
            "mempool_empty_sig_refuse_total": int(
                getattr(self, "_mempool_empty_sig_refuse_total", 0) or 0
            ),
            "mempool_empty_pubkey_refuse_total": int(
                getattr(self, "_mempool_empty_pubkey_refuse_total", 0) or 0
            ),
            "mempool_sig_size_refuse_total": int(
                getattr(self, "_mempool_sig_size_refuse_total", 0) or 0
            ),
            "mempool_pubkey_size_refuse_total": int(
                getattr(self, "_mempool_pubkey_size_refuse_total", 0) or 0
            ),
            "mempool_nonfinite_value_refuse_total": int(
                getattr(self, "_mempool_nonfinite_value_refuse_total", 0) or 0
            ),
            "mempool_nonfinite_fee_refuse_total": int(
                getattr(self, "_mempool_nonfinite_fee_refuse_total", 0) or 0
            ),
            "get_blocks_future_refuse_total": int(
                getattr(self, "_get_blocks_future_refuse_total", 0) or 0
            ),
            "get_block_future_refuse_total": int(
                getattr(self, "_get_block_future_refuse_total", 0) or 0
            ),
            "get_blocks_past_tip_clamp_total": int(
                getattr(self, "_get_blocks_past_tip_clamp_total", 0) or 0
            ),
            "get_mempool_tip_misaligned_total": int(
                getattr(self, "_get_mempool_tip_misaligned_total", 0) or 0
            ),
            "bootstrap_redial_total": int(
                getattr(self, "_bootstrap_redial_total", 0) or 0
            ),
            "bootstrap_pin_rejects_total": int(
                getattr(self, "_bootstrap_pin_rejects_total", 0) or 0
            ),
            "bootstrap_pins_configured": len(bootstrap_pin_map(self.config)),
            "bootstrap_missing_count": len(self._missing_bootstrap_addrs())
            if getattr(self.config, "bootstrap_peers", None)
            else 0,
            "p2p_discovery_allow_private": bool(
                getattr(self.config, "p2p_discovery_allow_private", False)
            ),
            "native_message_loop_dispatch_total": int(
                getattr(self, "_native_message_loop_dispatch_total", 0) or 0
            ),
            "native_message_loop_strikes_total": int(
                getattr(self, "_native_message_loop_strikes_total", 0) or 0
            ),
            "native_transport_prod_required": bool(
                getattr(self.config, "p2p_native_transport", False)
                and (
                    bool(getattr(self.config, "require_native_crypto", False))
                    or str(getattr(self.config, "deployment_mode", "") or "").lower()
                    == "prod"
                )
            ),
            "native_shape_revalidate": not bool(getattr(self, "_use_native_transport", False)),
            "native_read_batch": int(getattr(self, "_native_read_batch", 8) or 8),
            "native_write_batch": int(getattr(self, "_native_write_batch", 8) or 8),
            "native_read_chunk": int(getattr(self, "_native_read_chunk", 65536) or 65536),
            "native_io_timeout_ms": int(
                getattr(self, "_native_io_timeout_ms", 30000) or 30000
            ),
            "native_accept_total": int(self._native_accept_total or 0),
            "native_accept_errors": int(self._native_accept_errors or 0),
            "native_connect_total": int(self._native_connect_total or 0),
            "max_inbound_per_ip": int(getattr(self.config, "p2p_max_inbound_per_ip", 0) or 0),
            "max_peers_per_subnet": int(
                getattr(self.config, "p2p_max_peers_per_subnet", 0) or 0
            ),
            "reserved_outbound_slots": int(
                getattr(self.config, "p2p_reserved_outbound_slots", 0) or 0
            ),
            "eclipse_warn_ratio": float(
                getattr(self.config, "p2p_eclipse_warn_ratio", 0) or 0
            ),
            "subnet_rejects": (
                int(getattr(self._conn_governor, "subnet_rejects", 0) or 0)
                if self._conn_governor is not None
                else 0
            ),
            "reserved_slot_rejects": (
                int(getattr(self._conn_governor, "reserved_slot_rejects", 0) or 0)
                if self._conn_governor is not None
                else 0
            ),
            "eclipse_ratio": float(self._eclipse_ratio or 0),
            "eclipse_at_risk": bool(self._eclipse_at_risk),
            "unique_public_subnets": int(self._eclipse_unique_public_subnets or 0),
            "public_peers": int(self._eclipse_public_peers or 0),
            "eclipse_prune_total": int(self._eclipse_prune_total or 0),
            "max_bytes_per_sec": int(getattr(self.config, "p2p_max_bytes_per_sec", 0) or 0),
            "max_outbound_bytes_per_sec": int(
                getattr(self.config, "p2p_max_outbound_bytes_per_sec", 0) or 0
            ),
            "bandwidth_rejects": int(bw_rejects),
            "egress_rejects": int(eg_rejects),
            "handshake_rejects": int(self._handshake_rejects),
            "attestation_local_fail": int(self._attestation_local_fail),
            "shape_rejects_total": int(sum(self._shape_reject_counts.values())),
            "shape_rejects": dict(
                sorted(
                    self._shape_reject_counts.items(),
                    key=lambda kv: (-int(kv[1]), str(kv[0])),
                )[:32]
            ),
            "rate_limit_drops": int(
                self._shape_reject_counts.get("rate_limit_exceeded", 0) or 0
            ),
            "rate_limit_class_drops": int(
                self._shape_reject_counts.get("rate_limit_class_exceeded", 0) or 0
            ),
            "ops_errors": {
                "propagation_log_fail": int(self._propagation_log_fail),
                "peer_connect_task_fail": int(self._peer_connect_task_fail),
                "peer_status_send_fail": int(self._peer_status_send_fail),
                "peer_send_fail": int(self._peer_send_fail),
                "broadcast_fail": int(self._broadcast_fail),
                "maintenance_loop_fail": int(self._maintenance_loop_fail),
                "catch_up_loop_fail": int(self._catch_up_loop_fail),
                "peer_tx_reject": int(self._peer_tx_reject),
                "import_block_fail": int(self._import_block_fail),
                "import_offload_total": int(self._import_offload_total),
                "sync_fail": int(self._sync_fail),
                "peer_sync_fail": int(self._peer_sync_fail),
                "discovery_loop_fail": int(self._discovery_loop_fail),
                "bootstrap_loop_fail": int(self._bootstrap_loop_fail),
            },
            "rate_limit_exempt_types": len(RATE_LIMIT_EXEMPT_TYPES),
            "outbound_drops": int(self._outbound_drops or 0),
            "sync_admission_rejects": int(self._sync_admission_rejects or 0),
            "sync_inflight": sum(
                1 for t in (self._sync_tasks or {}).values() if t and not t.done()
            ),
            "max_sync_inflight": max(
                1, int(getattr(self.config, "p2p_max_sync_inflight", 2) or 2)
            ),
            "send_queue_max": int(getattr(self.config, "p2p_send_queue_max", 256) or 256),
            "drain_timeout_sec": float(
                getattr(self.config, "p2p_drain_timeout_sec", 5.0) or 5.0
            ),
            "exempt_messages_per_sec": int(
                getattr(self.config, "p2p_exempt_messages_per_sec", 0) or 0
            ),
            "attest_messages_per_sec": int(
                getattr(self.config, "p2p_attest_messages_per_sec", 0) or 0
            ),
            "tx_messages_per_sec": int(
                getattr(self.config, "p2p_tx_messages_per_sec", 0) or 0
            ),
            "block_announce_messages_per_sec": int(
                getattr(self.config, "p2p_block_announce_messages_per_sec", 0) or 0
            ),
            "tls": p2p_tls_status(self.config),
        }
        shadow = getattr(self, "tip_safety_shadow", None)
        if shadow is not None and hasattr(shadow, "merge_into_status"):
            try:
                shadow.merge_into_status(status)
            except Exception as exc:
                logger.warning("[P2P] tip_safety shadow status merge failed: %s", exc)
        else:
            status.setdefault("tip_safety_shadow_enabled", False)
        adapter = getattr(self, "transport_adapter", None)
        if adapter is not None and hasattr(adapter, "merge_into_status"):
            try:
                adapter.merge_into_status(status)
            except Exception as exc:
                logger.warning("[P2P] transport adapter status merge failed: %s", exc)
        else:
            status.setdefault("transport_boundary", False)
        dispatcher = getattr(self, "dispatcher", None)
        if dispatcher is not None and hasattr(dispatcher, "merge_into_status"):
            try:
                dispatcher.merge_into_status(status)
            except Exception as exc:
                logger.warning("[P2P] dispatcher status merge failed: %s", exc)
        else:
            status.setdefault("dispatch_boundary", False)
        eng = getattr(self, "sync_engine", None)
        cons = getattr(eng, "consistency", None) if eng is not None else None
        if cons is not None and hasattr(cons, "merge_into_status"):
            try:
                cons.merge_into_status(status)
            except Exception as exc:
                logger.warning("[P2P] consistency status merge failed: %s", exc)
        else:
            status.setdefault("consistency_boundary", False)
        hub = getattr(self, "solicit_hub", None)
        if hub is not None and hasattr(hub, "merge_into_status"):
            try:
                hub.merge_into_status(status)
            except Exception as exc:
                logger.warning("[P2P] solicit hub status merge failed: %s", exc)
                status.setdefault("solicit_hub", True)
        else:
            status.setdefault("solicit_hub", False)
        try:
            status["libp2p"] = self._libp2p_status_block()
        except Exception as exc:
            logger.warning("[P2P] libp2p status merge failed: %s", exc)
            status["libp2p"] = {
                "feature_libp2p": bool(getattr(self.config, "feature_libp2p", False)),
                "error": str(exc),
                "honesty": "ADR0019_rust_libp2p_lab_not_prod_mesh",
            }
        return status

    def _libp2p_status_block(self) -> Dict:
        """libp2p metrics for /status. ADR 0020 when the live swarm is listening."""
        from network.transport.libp2p_adapter.status_metrics import (
            empty_libp2p_status_metrics,
            merge_libp2p_status_metrics,
        )

        feature = bool(getattr(self.config, "feature_libp2p", False))
        listening = bool(getattr(self, "_libp2p_listening", False))
        block: Dict = {
            "feature_libp2p": feature,
            "active": bool(feature and listening),
            "default_mesh": bool(feature and listening),
            "honesty": (
                "ADR0020_experimental_libp2p_industrial_mesh"
                if feature and listening
                else "ADR0019_rust_libp2p_lab_not_prod_mesh"
            ),
            "peer_policy": False,
            "rust_backend": False,
            "listen_addrs": list(getattr(self, "_libp2p_listen_addrs", []) or []),
            "wire_refuse_total": int(getattr(self, "_libp2p_wire_refuse_total", 0) or 0),
        }
        block.update(empty_libp2p_status_metrics())
        ds = getattr(self, "_dual_stack", None)
        if ds is None:
            return block
        try:
            caps = dict(ds.capability_status() or {})
            lib = dict(caps.get("libp2p") or {})
            block["rust_backend"] = bool(lib.get("rust_backend") or lib.get("noise"))
            pol = lib.get("peer_policy") if isinstance(lib.get("peer_policy"), dict) else {}
            block["peer_policy"] = bool(pol.get("attached"))
            merge_libp2p_status_metrics(block, lib)
            merge_libp2p_status_metrics(block, dict(ds.metrics() or {}))
            if listening:
                block["active"] = True
                block["default_mesh"] = True
                block["honesty"] = "ADR0020_experimental_libp2p_industrial_mesh"
        except Exception as exc:
            block["error"] = str(exc)
        return block
