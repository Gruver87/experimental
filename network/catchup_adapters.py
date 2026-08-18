"""P2P → CatchUpPath A port adapters (ADR 0004 Step B).

Each class implements exactly one port protocol from ``sync.ports``.
No sync domain logic here: just threading bridges between P2P asyncio
coroutines and the synchronous ``CatchUpPathAService``.

Design contract
---------------
* ``CatchUpP2PFetchAdapter`` and ``CatchUpP2PProbeAdapter`` are instantiated
  fresh per ``_sync_with_peer`` call so they capture the correct event-loop
  and peer reference for that invocation.
* ``CatchUpP2PChainAdapter`` and ``CatchUpP2PSideEffectAdapter`` are
  stateless wrappers around P2PNode attributes and can be shared.
* No ``network.p2p_node`` symbols are imported at module level — only
  referenced through duck-typed parameters to avoid cycles.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Dict, Mapping, Optional, Sequence

logger = logging.getLogger("P2P.CatchUpAdapter")

# Wire message constants (duplicated to avoid importing p2p_node at module level).
_MSG_GET_BLOCKS = "get_blocks"
_MSG_BLOCKS = "blocks"
_MSG_GET_BLOCK_BY_HASH = "get_block_by_hash"
_MSG_BLOCK = "block"
_MSG_STATE_ROOT_REQUEST = "state_root_request"
_MSG_STATE_ROOT_RESPONSE = "state_root_response"


# ── Chain port ────────────────────────────────────────────────────────────────


class CatchUpP2PChainAdapter:
    """Implements ``CatchUpChainPort`` over P2PNode blockchain + apply_queue.

    ``import_block`` delegates to ``p2p.import_block`` which includes the
    tip-safety path (ADR 0001 / ADR 0004 locked requirement).
    Reorg runs synchronously via ``asyncio.to_thread`` called from the
    fetch adapter's thread-pool bridge (handled by the service caller).
    """

    __slots__ = ("_p2p", "_loop")

    def __init__(
        self,
        p2p: Any,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._p2p = p2p
        self._loop = loop

    def height(self) -> int:
        return int(self._p2p.blockchain.get_height() or 0)

    def head(self) -> str:
        try:
            return str(self._p2p.head() or "")
        except Exception as exc:
            logger.warning("[CatchUpChain] head failed: %s", exc)
            return ""

    def expected_parent(self, height: int) -> str:
        try:
            return str(self._p2p._expected_parent_for_height(int(height)) or "")
        except Exception as exc:
            logger.warning("[CatchUpChain] expected_parent failed: %s", exc)
            return "0" * 64

    def get_block(self, height_or_hash: Any) -> Any:
        try:
            return self._p2p.get_block(height_or_hash)
        except Exception as exc:
            logger.warning("[CatchUpChain] get_block failed: %s", exc)
            return None

    def import_block(self, data: Mapping[str, Any]) -> bool:
        """Synchronous: calls P2PNode.import_block (tip-safety path)."""
        try:
            return bool(self._p2p.import_block(dict(data)))
        except Exception as exc:
            logger.warning("[CatchUpChain] import_block failed: %s", exc)
            return False

    def find_ancestor_height(self, parent_hash: str) -> Optional[int]:
        bc = self._p2p.blockchain
        if hasattr(bc, "find_ancestor_height"):
            try:
                return bc.find_ancestor_height(str(parent_hash or ""))
            except Exception as exc:
                logger.warning("[CatchUpChain] find_ancestor_height failed: %s", exc)
                return None
        key = str(parent_hash or "").strip()
        blk = None
        if hasattr(bc, "get_block_by_hash"):
            try:
                blk = bc.get_block_by_hash(key)
            except Exception as exc:
                logger.warning("[CatchUpChain] get_block_by_hash failed: %s", exc)
        if isinstance(blk, dict):
            try:
                return int(blk.get("height", blk.get("number", -1)) or -1)
            except (TypeError, ValueError):
                return None
        return None

    def reorg_to_ancestor(self, height: int) -> bool:
        bc = self._p2p.blockchain
        if not hasattr(bc, "reorg_to_ancestor"):
            return False
        q = getattr(self._p2p, "apply_queue", None)
        if q is not None:
            loop = self._loop
            if loop is None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    try:
                        loop = asyncio.get_event_loop()
                    except Exception as exc:
                        logger.debug("[CatchUpChain] get_event_loop failed: %s", exc)
                        loop = None
            if loop is None or not loop.is_running():
                logger.warning("[CatchUpChain] reorg via queue: no running loop")
                return False
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    q.submit_reorg_async(int(height)), loop
                )
                return bool(fut.result(timeout=30))
            except Exception as exc:
                logger.warning("[CatchUpChain] reorg via queue failed: %s", exc)
                return False
        try:
            return bool(bc.reorg_to_ancestor(int(height)))
        except Exception as exc:
            logger.warning("[CatchUpChain] reorg direct failed: %s", exc)
            return False


# ── Fetch port ────────────────────────────────────────────────────────────────


class CatchUpP2PFetchAdapter:
    """Implements ``CatchUpFetchPort`` over P2PNode._wait_peer_response.

    Runs the async coroutine synchronously from the thread that
    ``CatchUpPathAService.run_ahead`` executes in (via asyncio event-loop
    bridge). The P2P event loop is captured once at construction time.
    """

    __slots__ = ("_p2p", "_peer", "_loop")

    def __init__(self, p2p: Any, peer: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._p2p = p2p
        self._peer = peer
        self._loop = loop

    def fetch_blocks(
        self,
        peer_id: str,
        from_height: int,
        to_height: int,
        parent_hash: str,
        *,
        timeout: float = 45.0,
    ) -> Optional[Sequence[Mapping[str, Any]]]:
        """Block until MSG_BLOCKS arrives or timeout.  Returns None on timeout."""
        peer = self._peer
        p2p = self._p2p
        from_h = int(from_height)
        to_h = int(to_height)
        ph = str(parent_hash or "")

        async def _coro() -> Optional[Dict]:
            return await p2p._wait_peer_response(
                peer,
                (_MSG_BLOCKS,),
                timeout=float(timeout),
                presend=lambda: peer.send(
                    _MSG_GET_BLOCKS, {"from_height": from_h, "to_height": to_h}
                ),
                request_ctx={
                    "kind": "blocks",
                    "from_height": from_h,
                    "to_height": to_h,
                    "parent_hash": ph,
                    "allow_empty": False,
                },
            )

        fut = asyncio.run_coroutine_threadsafe(_coro(), self._loop)
        try:
            msg = fut.result(timeout=float(timeout) + 5)
        except Exception as exc:
            logger.debug("[CatchUpFetch] wait failed: %s", exc)
            return None
        if msg is None or not isinstance(msg, dict):
            return None
        if msg.get("type") != _MSG_BLOCKS:
            return None
        data = msg.get("data")
        if data is None:
            return None
        if isinstance(data, list):
            return data
        return None


# ── Probe port ────────────────────────────────────────────────────────────────


class CatchUpP2PProbeAdapter:
    """Implements ``CatchUpProbePort`` over P2PNode wire-solicit probes."""

    __slots__ = ("_p2p", "_peer", "_loop")

    def __init__(self, p2p: Any, peer: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._p2p = p2p
        self._peer = peer
        self._loop = loop

    def local_tip_probe_refuse(self, peer: Any) -> str:
        return self._run_async(self._p2p._catch_up_local_tip_probe_refuse_reason(self._peer))

    def peer_head_probe_refuse(self, peer: Any) -> str:
        return self._run_async(self._p2p._catch_up_peer_head_probe_refuse_reason(self._peer))

    def _run_async(self, coro: Any) -> str:
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return str(fut.result(timeout=60) or "")
        except Exception as exc:
            logger.warning("[CatchUpProbe] probe failed: %s", exc)
            return "catch_up_probe_adapter_error"


# ── Side-effect port ──────────────────────────────────────────────────────────


class CatchUpP2PSideEffectAdapter:
    """Implements ``CatchUpSideEffectPort`` delegating to P2PNode bookkeeping."""

    __slots__ = ("_p2p", "_peer")

    def __init__(self, p2p: Any, peer: Any) -> None:
        self._p2p = p2p
        self._peer = peer

    def bump_refuse(self, reason: str) -> None:
        try:
            self._p2p._bump_catch_up_refuse(str(reason or ""))
        except Exception as exc:
            logger.warning("[CatchUpSide] bump_refuse failed: %s", exc)

    def note_import_fail(self, peer_id: str) -> None:
        try:
            self._p2p._note_peer_import_fail(self._peer)
        except Exception as exc:
            logger.warning("[CatchUpSide] note_import_fail failed: %s", exc)

    def set_peer_height(self, peer_id: str, height: int) -> None:
        try:
            self._peer.height = max(
                int(getattr(self._peer, "height", 0) or 0), int(height)
            )
        except Exception as exc:
            logger.warning("[CatchUpSide] set_peer_height failed: %s", exc)

    def is_running(self) -> bool:
        return bool(getattr(self._p2p, "_running", True))

    def batch_size(self) -> int:
        try:
            return max(1, int(self._p2p.config.sync_batch_size or 32))
        except Exception as exc:
            logger.debug("[CatchUpSide] batch_size failed; default 32: %s", exc)
            return 32

    def on_progress(self, message: str) -> None:
        logger.info("[PathA] %s", message)
        print(f"[P2P] {message}")


# ── Factory ───────────────────────────────────────────────────────────────────


def build_path_a_adapters(
    p2p: Any,
    peer: Any,
    loop: asyncio.AbstractEventLoop,
) -> tuple[
    CatchUpP2PChainAdapter,
    CatchUpP2PFetchAdapter,
    CatchUpP2PProbeAdapter,
    CatchUpP2PSideEffectAdapter,
]:
    """Build all four adapters for one ``_sync_with_peer`` invocation."""
    return (
        CatchUpP2PChainAdapter(p2p, loop),
        CatchUpP2PFetchAdapter(p2p, peer, loop),
        CatchUpP2PProbeAdapter(p2p, peer, loop),
        CatchUpP2PSideEffectAdapter(p2p, peer),
    )
