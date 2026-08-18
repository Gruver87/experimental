"""P2P → ForkReconcile port adapters (ADR 0005).

Thin façades only — no reconcile policy. Bridges asyncio solicit/reorg into
the synchronous ``ForkReconcileService``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger("P2P.ForkAdapter")


class ForkReconcileP2PChainAdapter:
    """Implements ``ForkReconcileChainPort`` over P2PNode chain + apply path."""

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
            logger.warning("[ForkChain] head failed: %s", exc)
            return ""

    def expected_parent(self, height: int) -> str:
        try:
            return str(self._p2p._expected_parent_for_height(int(height)) or "")
        except Exception as exc:
            logger.warning("[ForkChain] expected_parent failed: %s", exc)
            return "0" * 64

    def get_block(self, height_or_hash: Any) -> Any:
        try:
            return self._p2p.get_block(height_or_hash)
        except Exception as exc:
            logger.warning("[ForkChain] get_block failed: %s", exc)
            return None

    def find_ancestor_height(self, parent_hash: str) -> Optional[int]:
        bc = self._p2p.blockchain
        if hasattr(bc, "find_ancestor_height"):
            try:
                return bc.find_ancestor_height(str(parent_hash or ""))
            except Exception as exc:
                logger.warning("[ForkChain] find_ancestor_height failed: %s", exc)
                return None
        return None

    def reorg_and_import(self, rollback_to: int, block: Mapping[str, Any]) -> bool:
        """Synchronous bridge into async reorg+import (tip-safety via import path).

        When called from ``asyncio.to_thread``, prefer the captured main-loop
        handle (same pattern as Fetch/Probe adapters). ``get_event_loop()`` on
        a worker thread has no running loop and must not be the primary path.
        """
        p2p = self._p2p
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                try:
                    loop = asyncio.get_event_loop()
                except Exception as exc:
                    logger.debug("[ForkChain] get_event_loop failed: %s", exc)
                    loop = None
        try:
            if loop is not None and loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    p2p._reorg_and_import_async(int(rollback_to), dict(block)),
                    loop,
                )
                return bool(fut.result(timeout=60))
            if loop is not None:
                return bool(
                    loop.run_until_complete(
                        p2p._reorg_and_import_async(int(rollback_to), dict(block))
                    )
                )
        except Exception as exc:
            logger.warning(
                "[ForkChain] async reorg_and_import failed; using sync fallback: %s",
                exc,
            )
        # Fallback: sync worker path (still tip-safety via import_block).
        try:
            return bool(p2p._reorg_and_import(int(rollback_to), dict(block)))
        except Exception as exc:
            logger.warning("[ForkChain] reorg_and_import failed: %s", exc)
            return False


class ForkReconcileP2PFetchAdapter:
    """Implements ``ForkReconcileFetchPort`` over ``_request_block_by_hash``."""

    __slots__ = ("_p2p", "_peers", "_loop")

    def __init__(
        self,
        p2p: Any,
        peers_by_id: Mapping[str, Any],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._p2p = p2p
        self._peers = peers_by_id
        self._loop = loop

    def fetch_block_by_hash(
        self,
        peer_id: str,
        block_hash: str,
        *,
        timeout: float = 30.0,
    ) -> Optional[Mapping[str, Any]]:
        peer = self._peers.get(str(peer_id or ""))
        if peer is None:
            return None
        hh = str(block_hash or "").strip()
        if not hh:
            return None

        async def _coro() -> Optional[Dict]:
            return await self._p2p._request_block_by_hash(peer, hh)

        fut = asyncio.run_coroutine_threadsafe(_coro(), self._loop)
        try:
            blk = fut.result(timeout=float(timeout) + 5)
        except Exception as exc:
            logger.debug("[ForkFetch] wait failed: %s", exc)
            return None
        if isinstance(blk, Mapping):
            return blk
        return None


class ForkReconcileP2PProbeAdapter:
    """Implements ``ForkReconcileProbePort`` over P2P fork/GHOST probes."""

    __slots__ = ("_p2p", "_peer", "_loop")

    def __init__(self, p2p: Any, peer: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._p2p = p2p
        self._peer = peer
        self._loop = loop

    def fork_peer_head_probe_refuse(self, peer: Any) -> str:
        return self._run_async(
            self._p2p._fork_peer_head_probe_refuse_reason(self._peer)
        )

    def ghost_head_probe_refuse(self, ghost_head: str, peer_hint: Any = None) -> str:
        return self._run_async(
            self._p2p._ghost_head_probe_refuse_reason(
                str(ghost_head or ""), peer_hint=self._peer
            )
        )

    def _run_async(self, coro: Any) -> str:
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return str(fut.result(timeout=60) or "")
        except Exception as exc:
            logger.warning("[ForkProbe] probe failed: %s", exc)
            return "fork_probe_adapter_error"


class ForkReconcileP2PSideEffectAdapter:
    """Implements ``ForkReconcileSideEffectPort`` including security Evidence."""

    __slots__ = ("_p2p", "_peer", "_malicious_attempts", "_evidence_log")

    def __init__(self, p2p: Any, peer: Any) -> None:
        self._p2p = p2p
        self._peer = peer
        self._malicious_attempts: Dict[str, int] = {}
        self._evidence_log: List[Any] = []

    def bump_refuse(self, reason: str) -> None:
        r = str(reason or "")
        try:
            if r.startswith("fork_"):
                self._p2p._bump_fork_probe_refuse(r)
                if r == "fork_same_height_spam":
                    self._p2p.bump_counter("fork_same_height_spam_total")
            elif r.startswith("ghost_"):
                self._p2p._bump_ghost_probe_refuse(r)
            elif r == "reconcile_head_hash_mismatch":
                self._p2p._reconcile_head_hash_mismatch_total = int(
                    getattr(self._p2p, "_reconcile_head_hash_mismatch_total", 0) or 0
                ) + 1
            elif r == "reconcile_contiguous_parent_mismatch":
                self._p2p._reconcile_contiguous_parent_mismatch_total = int(
                    getattr(
                        self._p2p, "_reconcile_contiguous_parent_mismatch_total", 0
                    )
                    or 0
                ) + 1
            elif r == "reconcile_same_height_parent_mismatch":
                self._p2p._reconcile_same_height_parent_mismatch_total = int(
                    getattr(
                        self._p2p, "_reconcile_same_height_parent_mismatch_total", 0
                    )
                    or 0
                ) + 1
            elif r == "reconcile_tip_head_mismatch":
                self._p2p._reconcile_tip_head_mismatch_total = int(
                    getattr(self._p2p, "_reconcile_tip_head_mismatch_total", 0) or 0
                ) + 1
            elif r == "tip_evidence_enforce_refuse":
                self._p2p.bump_counter("dispatch_tip_evidence_refuse_total")
            if hasattr(self._p2p, "bump_counter"):
                self._p2p.bump_counter(f"fork_refuse_{r}_total")
        except Exception as exc:
            logger.warning("[ForkSide] bump_refuse failed: %s", exc)

    def set_peer_tip(self, peer_id: str, height: int, head_hash: str) -> None:
        peer = None
        if self._peer is not None and str(
            getattr(self._peer, "peer_id", "") or ""
        ) == str(peer_id or ""):
            peer = self._peer
        else:
            peer = (getattr(self._p2p, "peers", {}) or {}).get(str(peer_id or ""))
        if peer is None:
            return
        try:
            peer.height = int(height)
            peer.head = str(head_hash or "")
        except Exception as exc:
            logger.warning("[ForkSide] set_peer_tip failed: %s", exc)

    def ghost_canonical_head(self) -> str:
        try:
            return str(self._p2p._ghost_canonical_head() or "")
        except Exception as exc:
            logger.warning("[ForkSide] ghost_canonical_head failed: %s", exc)
            return ""

    def peer_ids_for_head(self, head_hash: str) -> Sequence[str]:
        want = str(head_hash or "").strip().lower()
        out: List[str] = []
        if not want:
            return out
        for pid, peer in (getattr(self._p2p, "peers", {}) or {}).items():
            head = str(getattr(peer, "head", "") or "").strip().lower()
            if head and head == want:
                out.append(str(pid))
        return out

    def all_peer_ids(self) -> Sequence[str]:
        return [str(pid) for pid in (getattr(self._p2p, "peers", {}) or {}).keys()]

    def note_reorg_risk(self) -> None:
        predictor = getattr(self._p2p, "reorg_predictor", None)
        if predictor is None or not hasattr(predictor, "analyze_live_peers"):
            return
        try:
            peer_heights = [
                int(getattr(p, "height", 0) or 0)
                for p in (getattr(self._p2p, "peers", {}) or {}).values()
            ]
            risk = predictor.analyze_live_peers(
                int(self._p2p.blockchain.get_height() or 0), peer_heights
            )
            if float(risk.get("risk", 0) or 0) > 0.5:
                print(
                    f"[P2P] High reorg risk ({risk.get('risk'):.2f}) — "
                    f"proceeding with finality guard"
                )
        except Exception as exc:
            logger.warning("[ForkSide] note_reorg_risk failed: %s", exc)

    def is_running(self) -> bool:
        return bool(getattr(self._p2p, "_running", True))

    def on_progress(self, message: str) -> None:
        logger.info("[Fork] %s", message)
        print(f"[P2P] {message}")

    def tip_evidence_refuse(self, block: Mapping[str, Any]) -> str:
        bridge = getattr(self._p2p, "_tip_evidence_bridge", None)
        if bridge is None or not hasattr(bridge, "evaluate_block_candidate"):
            return ""
        try:
            decision = bridge.evaluate_block_candidate(
                dict(block), getattr(self._p2p, "blockchain", None)
            )
        except Exception as exc:
            logger.warning("[Fork] tip evidence evaluate failed: %s", exc)
            return ""
        if decision is None:
            return ""
        if bool(getattr(decision, "enforce_refuse", False)):
            return str(
                getattr(decision, "reason_code", "") or "tip_evidence_enforce_refuse"
            )
        if getattr(decision, "ok", True) is False and bool(
            getattr(bridge, "enforce", False)
        ):
            return str(
                getattr(decision, "reason_code", "") or "tip_evidence_enforce_refuse"
            )
        return ""

    def note_malicious_attempt(self, peer_id: str, reason: str) -> int:
        key = f"{peer_id}:{reason}"
        n = int(self._malicious_attempts.get(key, 0) or 0) + 1
        self._malicious_attempts[key] = n
        # Also aggregate per-peer across reasons for spam threshold.
        peer_key = str(peer_id or "")
        total = int(self._malicious_attempts.get(peer_key, 0) or 0) + 1
        self._malicious_attempts[peer_key] = total
        return total

    def emit_security_evidence(self, evidence: Any) -> None:
        self._evidence_log.append(evidence)
        payload = (
            evidence.to_bus_payload()
            if hasattr(evidence, "to_bus_payload")
            else {"evidence": str(evidence)}
        )
        try:
            self._p2p.bump_counter("fork_security_evidence_total")
        except Exception as exc:
            logger.warning("[ForkSide] bump_counter failed: %s", exc)
        # Persist last evidence on the node for status / ops.
        try:
            self._p2p._last_fork_security_evidence = dict(payload)
        except Exception as exc:
            logger.warning("[ForkSide] persist last evidence failed: %s", exc)
        bus = getattr(self._p2p, "bus", None)
        if bus is not None and hasattr(bus, "emit"):
            try:
                bus.emit("security.fork_refuse", payload)
            except Exception as exc:
                logger.warning("[Fork] security bus emit failed: %s", exc)
        logger.warning(
            "[Fork] SECURITY EVIDENCE peer=%s reason=%s attempts=%s",
            str(payload.get("peer_id", ""))[:12],
            payload.get("reason_code"),
            payload.get("attempt_count"),
        )

    def strike_malicious_peer(self, peer_id: str, reason: str) -> bool:
        peer = None
        if self._peer is not None and str(
            getattr(self._peer, "peer_id", "") or ""
        ) == str(peer_id or ""):
            peer = self._peer
        else:
            peer = (getattr(self._p2p, "peers", {}) or {}).get(str(peer_id or ""))
        if peer is None:
            return False
        try:
            banned = bool(self._p2p.strike_peer(peer, str(reason or "fork_malicious")))
            if banned:
                self._p2p.remove_peer(str(peer_id or ""), peer)
            return banned
        except Exception as exc:
            logger.warning("[Fork] strike failed: %s", exc)
            return False


def build_fork_reconcile_adapters(
    p2p: Any,
    peer: Any,
    loop: asyncio.AbstractEventLoop,
) -> tuple[
    ForkReconcileP2PChainAdapter,
    ForkReconcileP2PFetchAdapter,
    ForkReconcileP2PProbeAdapter,
    ForkReconcileP2PSideEffectAdapter,
]:
    peers_by_id = dict(getattr(p2p, "peers", {}) or {})
    if peer is not None:
        pid = str(getattr(peer, "peer_id", "") or "")
        if pid and pid not in peers_by_id:
            peers_by_id[pid] = peer
    return (
        ForkReconcileP2PChainAdapter(p2p, loop),
        ForkReconcileP2PFetchAdapter(p2p, peers_by_id, loop),
        ForkReconcileP2PProbeAdapter(p2p, peer, loop),
        ForkReconcileP2PSideEffectAdapter(p2p, peer),
    )
