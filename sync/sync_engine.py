# sync/sync_engine.py
"""
Sync Engine — fast catch-up for late-joining nodes
- Peer head resolution
- Chain download (headers → blocks)
- State reconciliation (fail-closed ConsistencyService, ADR 0003)
"""

from typing import List, Dict, Optional, Any
import logging
import time

logger = logging.getLogger("Sync.Engine")

from crypto import native
from sync.consistency import (
    ConsistencyService,
    InMemoryConsistencyStore,
    PeerSyncView,
    WireProbeResult,
)


class SyncEngine:
    """
    Fast sync engine with deterministic head selection and fail-closed block import.
    """

    def __init__(self, node, consistency: Optional[ConsistencyService] = None):
        self.node = node
        self.peers = []
        self.is_syncing = False
        self.sync_progress = 0
        self._solo_log_last_ts = 0.0
        self._solo_log_interval_sec = 300.0  # intentional solo: avoid per-block spam
        self._wire_probe_fail_ts = 0.0
        self._wire_probe_backoff_sec = 8.0
        self._wire_sticky_empty_streak = 0
        self._wire_sticky_empty_max = 3
        self._last_wire_probe_ok = None
        self._sync_fail = 0
        self._last_sync_error = ""
        self._last_sync_ok_at = 0
        self._heads_skipped_no_head = 0
        if consistency is not None:
            self.consistency = consistency
        else:
            store = InMemoryConsistencyStore(on_change=self._on_consistency_change)
            self.consistency = ConsistencyService(store)

    def add_peer(self, peer):
        """Добавляет пира для синхронизации"""
        if peer not in self.peers:
            self.peers.append(peer)

    def remove_peer(self, peer):
        if peer in self.peers:
            self.peers.remove(peer)

    def get_peers(self) -> List:
        return self.peers

    def _collect_p2p_peers(self) -> List:
        """Peers from AbsoluteNode.p2p, P2PNode itself, or explicit sync peer list."""
        p2p = getattr(self.node, "p2p", None)
        if p2p is not None and getattr(p2p, "peers", None):
            live = list(p2p.peers.values())
            if live:
                return live
        # SyncEngine(node=P2PNode) boot path before AbsoluteNode replaces the engine.
        if getattr(self.node, "peers", None) and not hasattr(self.node, "p2p"):
            live = list(self.node.peers.values())
            if live:
                return live
        return list(self.peers)

    def request_heads(self) -> List[Dict]:
        """Collect head hashes from connected P2P peers.

        v1.3.140: never invent peer.head from the local block at peer.height —
        empty head means the peer is not eligible for head selection (aligns
        with p2p_catch_up_require_head). Soft honesty only — not tip proof.
        """
        heads = []
        skipped_no_head = 0
        for peer in self._collect_p2p_peers():
            head_raw = getattr(peer, "head", None)
            head_hash = ""
            if isinstance(head_raw, dict):
                head_hash = head_raw.get("hash", "")
            elif isinstance(head_raw, str):
                head_hash = head_raw
            head_hash = str(head_hash or "").strip()
            if not head_hash:
                if int(getattr(peer, "height", 0) or 0) > 0:
                    skipped_no_head += 1
                continue
            heads.append({
                "hash": head_hash,
                "height": int(getattr(peer, "height", 0) or 0),
                "peer_id": getattr(peer, "peer_id", ""),
            })
        self._heads_skipped_no_head = int(skipped_no_head)
        return heads

    def select_best_head(self, heads: List[Dict]) -> Optional[str]:
        """
        LMD-GHOST cumulative weight when consensus is available;
        otherwise highest peer height (longest chain).
        """
        if not heads:
            return None

        best_head = None
        best_key = (-1, -1)  # (weight, height)

        consensus = getattr(self.node, "consensus", None)
        for head_info in heads:
            if isinstance(head_info, dict):
                head_hash = head_info.get("hash", "")
                height = int(head_info.get("height", 0) or 0)
            else:
                head_hash = str(head_info)
                height = 0
            if not head_hash:
                continue

            weight = 0
            if consensus and hasattr(consensus, "get_cumulative_weight"):
                weight = int(consensus.get_cumulative_weight(head_hash) or 0)

            key = (weight, height)
            if key > best_key:
                best_key = key
                best_head = head_hash

        return best_head

    def _resolve_block(self, block_hash: str) -> Optional[Dict]:
        """Local DB first, then P2P peer fetch."""
        if hasattr(self.node, "get_block"):
            blk = self.node.get_block(block_hash)
            if blk:
                return blk
        if hasattr(self.node, "blockchain"):
            blk = self.node.blockchain.get_block_by_hash(block_hash)
            if blk:
                return blk
        p2p = getattr(self.node, "p2p", None)
        if p2p is None and hasattr(self.node, "fetch_block_from_peers_sync"):
            p2p = self.node
        if p2p and hasattr(p2p, "fetch_block_from_peers_sync"):
            return p2p.fetch_block_from_peers_sync(block_hash, timeout=45)
        return None

    def _local_height(self) -> int:
        if hasattr(self.node, "blockchain") and self.node.blockchain:
            return int(self.node.blockchain.get_height())
        if hasattr(self.node, "get_height"):
            return int(self.node.get_height() or 0)
        return 0

    @staticmethod
    def _block_height(block: Dict) -> int:
        if "height" in block and block.get("height") is not None:
            try:
                return int(block.get("height"))
            except (TypeError, ValueError):
                pass
        if "number" in block and block.get("number") is not None:
            try:
                return int(block.get("number"))
            except (TypeError, ValueError):
                pass
        return 0

    @staticmethod
    def _block_hash(block: Dict) -> str:
        return str(block.get("hash", ""))

    @staticmethod
    def _parent_hash(block: Dict) -> str:
        return str(block.get("parent_hash") or block.get("parent") or "")

    def _validate_downloaded_chain(self, chain: List[Dict], local_height: int) -> bool:
        """Require contiguous parent links and canonical block hashes before import."""
        previous_hash = ""
        if chain and hasattr(self.node, "blockchain") and self.node.blockchain:
            local_head = self.node.blockchain.get_block(local_height)
            if local_head:
                previous_hash = self._block_hash(local_head)
        return native.validate_imported_block_chain(
            chain,
            expected_parent_hash=previous_hash,
            start_height=local_height,
        )

    def _local_needs_genesis(self) -> bool:
        """True when the local store has no block #0 (follower empty tip)."""
        bc = getattr(self.node, "blockchain", None)
        if bc is None:
            return False
        try:
            if hasattr(bc, "get_last_block"):
                return bc.get_last_block() is None
        except Exception as exc:
            logger.warning("get_last_block failed in _local_needs_genesis: %s", exc)
            try:
                return int(self._local_height() or 0) <= 0
            except Exception:
                return True
        return False

    def download_chain(self, head: str, stop_at_height: Optional[int] = None) -> List[Dict]:
        """Walk parent chain from head; stop at a block we already have locally.

        ``stop_at_height=-1`` includes genesis (height 0) — required when the
        local DB is empty and followers must import the leader's block #0.
        """
        chain = []
        current = head
        seen = set()
        if stop_at_height is None:
            stop_h = -1 if self._local_needs_genesis() else self._local_height()
        else:
            stop_h = int(stop_at_height)

        while current and current not in seen:
            seen.add(current)
            block = None
            if hasattr(self.node, "blockchain") and self.node.blockchain:
                block = self.node.blockchain.get_block_by_hash(current)
            if not block:
                block = self._resolve_block(current)
            if not block:
                break

            height = self._block_height(block)
            if height <= stop_h:
                break

            chain.append(block)
            current = self._parent_hash(block)
            if len(chain) > 10000:
                break

        return list(reversed(chain))

    def fast_sync(self, target_block: int = 0) -> bool:
        """Ahead catch-up via shared ``CatchUpPathAService`` (ADR 0004 Step C).

        Peer/head selection and consistency stay on SyncEngine. The former
        private download→import I/O loop is gone: Path A ``run_ahead`` owns
        batch fetch/import through CatchUp* ports (``SyncEngineCatchUpIO``).
        """
        if self.is_syncing:
            print("[Sync] Already in progress")
            return False

        local_h = self._local_height()
        print(f"[Sync] Starting fast sync from height {local_h}...")
        self.is_syncing = True
        ok = False
        try:
            heads = self.request_heads()
            if not heads:
                print("[Sync] No peers available")
                self._last_sync_error = "no_peers"
                return False

            best_head = self.select_best_head(heads)
            if not best_head:
                print("[Sync] No valid head selected")
                self._last_sync_error = "no_valid_head"
                return False

            # Prefer the selected head's peer height; fall back to max claimed.
            best_peer_h = 0
            best_peer_id = ""
            for h in heads:
                hh = str(h.get("hash") or "").strip()
                ph = int(h.get("height", 0) or 0)
                if hh == best_head:
                    best_peer_h = ph
                    best_peer_id = str(h.get("peer_id") or "")
                    break
            if best_peer_h <= 0:
                best_peer_h = max(int(h.get("height", 0) or 0) for h in heads)
            if target_block > 0:
                best_peer_h = min(best_peer_h, int(target_block))

            needs_genesis = self._local_needs_genesis()
            # Empty follower tip reports height 0 — same as leader genesis height.
            # Still must import block #0; do not treat 0<=0 as "already at head".
            if best_peer_h <= local_h and not needs_genesis:
                print(f"[Sync] Already at head (local={local_h}, peer={best_peer_h})")
                ok = bool(self.sync_state())
                if ok:
                    self._last_sync_ok_at = int(time.time())
                    self._last_sync_error = ""
                else:
                    self._last_sync_error = "state_sync_failed"
                return ok
            if needs_genesis:
                print(
                    f"[Sync] Empty local chain: importing genesis from peer "
                    f"(peer height {best_peer_h}, head={best_head[:8]}...)"
                )

            print(f"[Sync] Selected head: {best_head[:8]}... (peer height {best_peer_h})")

            from sync.catchup.engine_io import SyncEngineCatchUpIO
            from sync.catchup.path_a import CatchUpPathAService
            from sync.catchup.types import CatchUpConfig, CatchUpPeerView, CatchUpStatus

            io = SyncEngineCatchUpIO(
                self,
                peer_id=best_peer_id or "fast_sync",
                peer_head=best_head,
                target_height=int(best_peer_h),
                batch_size=32,
                running=True,
            )
            # Materialise ahead index early so tip-head bind cites the hash
            # at the (possibly target-capped) height, not the uncapped peer tip.
            io._ensure_ahead_index()
            tip_blk = io._by_height.get(int(best_peer_h))
            bind_head = best_head
            if isinstance(tip_blk, dict):
                tip_hh = str(
                    tip_blk.get("hash") or tip_blk.get("block_hash") or ""
                ).strip()
                if tip_hh:
                    bind_head = tip_hh

            svc = CatchUpPathAService(
                chain=io,
                fetch=io,
                probe=io,
                side=io,
            )
            peer_view = CatchUpPeerView(
                peer_id=best_peer_id or "fast_sync",
                height=int(best_peer_h),
                head_hash=bind_head,
            )
            cfg = CatchUpConfig(
                batch_size=32,
                require_head=True,
                tip_head_bind=True,
                height_continuity_bind=True,
                contiguous_parent_bind=True,
                tip_probe_enabled=True,
                peer_head_probe_enabled=True,
                fetch_timeout=45.0,
            )
            outcome = svc.run_ahead(peer_view, cfg)
            self.sync_progress = int(outcome.imported or 0)

            if outcome.status is CatchUpStatus.REFUSED:
                self._last_sync_error = str(outcome.reason_code or "refused")
                print(f"[Sync] Catch-up refused: {self._last_sync_error}")
                return False
            if outcome.status is CatchUpStatus.STALLED:
                err = str(outcome.reason_code or "fetch_stall")
                if getattr(io, "_chain_error", ""):
                    err = str(io._chain_error)
                self._last_sync_error = err
                if err == "non_contiguous_chain":
                    print("[Sync] Downloaded chain is not contiguous")
                else:
                    print(f"[Sync] Chain download stalled: {err}")
                return False
            if outcome.status is CatchUpStatus.ERROR:
                self._sync_fail += 1
                self._last_sync_error = str(
                    outcome.reason_code or outcome.detail or "path_a_error"
                )
                print(f"[Sync] fast_sync error: {self._last_sync_error}")
                return False
            if (
                outcome.status is CatchUpStatus.INCOMPLETE
                and int(outcome.imported or 0) == 0
                and outcome.reason_code
                in ("empty_batch", "batch_no_progress", "fetch_stall")
            ):
                # No bodies served after head selection — treat as download fail
                # unless we already know a contiguity refuse was recorded.
                if "non_contiguous_chain" in getattr(io, "refuses", []):
                    self._last_sync_error = "non_contiguous_chain"
                    print("[Sync] Downloaded chain is not contiguous")
                    return False
                if getattr(io, "_chain_error", "") == "non_contiguous_chain":
                    self._last_sync_error = "non_contiguous_chain"
                    print("[Sync] Downloaded chain is not contiguous")
                    return False
                if not io.fetch_calls or getattr(io, "_chain_error", ""):
                    self._last_sync_error = (
                        getattr(io, "_chain_error", "") or "download_failed"
                    )
                    print("[Sync] Chain download failed")
                    return False

            if int(outcome.imported or 0) == 0 and outcome.status is CatchUpStatus.SKIPPED:
                print(f"[Sync] No new blocks (local={local_h})")
            elif int(outcome.imported or 0) == 0 and outcome.status is CatchUpStatus.INCOMPLETE:
                # Import aborted mid-way with zero progress after refuse gates,
                # or download yielded nothing useful.
                if outcome.reason_code and "import" in str(outcome.reason_code):
                    self._last_sync_error = str(outcome.reason_code)
                    return False

            # Tip bind / set_head after successful height catch-up.
            if outcome.reached_target or outcome.status is CatchUpStatus.COMPLETE:
                if hasattr(self.node, "consensus") and hasattr(
                    self.node.consensus, "set_head"
                ):
                    self.node.consensus.set_head(best_head)
                elif hasattr(self.node, "chain") and hasattr(self.node.chain, "set_head"):
                    self.node.chain.set_head(best_head)

            # Import-fail mid-batch: Path A returns incomplete; mirror old False.
            if (
                outcome.status is CatchUpStatus.INCOMPLETE
                and io.import_fails
                and not outcome.reached_target
            ):
                tip_now = self._local_height()
                self._last_sync_error = f"import_failed:{tip_now + 1}"
                print(f"[Sync] Import failed at height {tip_now + 1}")
                return False

            ok = bool(self.sync_state())
            if ok:
                self._last_sync_ok_at = int(time.time())
                self._last_sync_error = ""
            else:
                self._last_sync_error = "state_sync_failed"
            print(
                f"[Sync] Done: imported {int(outcome.imported or 0)} blocks "
                f"(local now {self._local_height()}; status={outcome.status.value})"
            )
            return ok
        except Exception as exc:
            self._sync_fail += 1
            self._last_sync_error = str(exc)
            print(f"[Sync] fast_sync failed: {exc}")
            return False
        finally:
            # Fail-closed: never leave is_syncing stuck after unexpected errors.
            self.is_syncing = False

    def _on_consistency_change(self, snap) -> None:
        """Mirror ConsistencyService snapshot onto node/P2P flags."""
        flag = bool(getattr(snap, "consistent", False))
        probe = getattr(snap, "probe", None)
        if probe is not None and getattr(probe, "probed", False):
            self._last_wire_probe_ok = probe.ok
        elif probe is not None and not getattr(probe, "probed", True):
            self._last_wire_probe_ok = None
        self._set_state_consistent(flag)

    def _peer_views(self) -> List[PeerSyncView]:
        views: List[PeerSyncView] = []
        for peer in self._collect_p2p_peers():
            head_raw = getattr(peer, "head", None)
            head_hash = ""
            if isinstance(head_raw, dict):
                head_hash = str(head_raw.get("hash") or "")
            else:
                head_hash = str(head_raw or "")
            views.append(
                PeerSyncView(
                    peer_id=str(getattr(peer, "peer_id", "") or ""),
                    height=int(getattr(peer, "height", 0) or 0),
                    head_hash=head_hash.strip(),
                    dial_key=str(getattr(peer, "dial_target", "") or ""),
                )
            )
        return views

    def _set_state_consistent(self, ok: bool) -> None:
        """Mirror consistency on AbsoluteNode and/or nested P2PNode."""
        flag = bool(ok)
        if hasattr(self.node, "_state_consistent"):
            self.node._state_consistent = flag
        p2p = getattr(self.node, "p2p", None)
        if p2p is not None and hasattr(p2p, "_state_consistent"):
            p2p._state_consistent = flag

    def reevaluate_consistency(self) -> bool:
        """Post catch-up / reconcile re-eval via ConsistencyService (ADR 0003)."""
        return bool(self.sync_state())

    def sync_state(self) -> bool:
        """Compare local state_root with peer-reported roots when available.

        same-height consistency only from wire roots (never invent via local
        get_block). Returns True only when ConsistencyService reports trusted
        consistent. Incomplete-ahead is BehindOpen → returns False
        (ADR 0003 fail-closed).
        """
        if not hasattr(self.node, "blockchain"):
            print("[Sync] Checking state consistency...")
            print("   No blockchain attached")
            self.consistency.request_lockdown("no_blockchain")
            return False

        bc = self.node.blockchain
        if not hasattr(bc, "get_state_root"):
            print("[Sync] Checking state consistency...")
            print("   [Sync] blockchain missing get_state_root — fail-closed")
            self.consistency.request_lockdown("no_get_state_root")
            return False

        local_root = str(bc.get_state_root() or "")
        local_height = int(bc.get_height() or 0)
        peers = self._peer_views()

        if not peers:
            # Keep this exact line in-source (industrial_gate needle). Rate-limit prints
            # so intentional solo mining does not flood the console every block.
            now = time.time()
            if (now - float(self._solo_log_last_ts or 0.0)) >= float(
                self._solo_log_interval_sec or 300.0
            ):
                print("[Sync] Checking state consistency...")
                print(
                    "   Solo / no peers — wire probe deferred (never-probed), fail-closed"
                )
                self._solo_log_last_ts = now
            decision = self.consistency.apply_probe_evaluation(
                peers=(),
                local_height=local_height,
                local_root=local_root,
                probe=WireProbeResult.never_probed("no_peers"),
            )
            return bool(decision.trusted)

        print("[Sync] Checking state consistency...")
        if not hasattr(self.node, "request_peer_state_roots_sync"):
            print(
                "   [Sync] request_peer_state_roots_sync missing with peers "
                "— fail-closed (never paint green without a real probe)"
            )
            decision = self.consistency.apply_probe_evaluation(
                peers=peers,
                local_height=local_height,
                local_root=local_root,
                probe=WireProbeResult.failed("probe_api_missing"),
            )
            return bool(decision.trusted)

        # Re-probe without wiping last-known green: request_probing keeps
        # consistent=True sticky while the wire solicit runs (see machine).
        now = time.time()
        fail_ts = float(getattr(self, "_wire_probe_fail_ts", 0.0) or 0.0)
        backoff = float(getattr(self, "_wire_probe_backoff_sec", 8.0))
        if backoff < 0.0:
            backoff = 0.0
        if fail_ts > 0.0 and (now - fail_ts) < backoff:
            print("   [Sync] wire probe backoff after timeout/empty")
            # Do not apply a synthetic failed probe — that overwrote a late
            # successful coalesced flight and kept topology_healthy false.
            return bool(self.consistency.snapshot().consistent)

        self.consistency.request_probing()
        wire_roots: List[Any] = []
        try:
            # Background tip trust can afford a longer solicit than HTTP quick harness.
            raw = self.node.request_peer_state_roots_sync(timeout=70)
            if raw is None:
                print("   [Sync] peer state_root wire probe failed: timeout/empty")
                self._wire_probe_fail_ts = time.time()
                if self.consistency.snapshot().consistent:
                    self._wire_sticky_empty_streak = int(
                        getattr(self, "_wire_sticky_empty_streak", 0) or 0
                    ) + 1
                    max_sticky = int(getattr(self, "_wire_sticky_empty_max", 3) or 3)
                    if self._wire_sticky_empty_streak < max_sticky:
                        print("   [Sync] wire probe backoff after timeout/empty")
                        return True
                    print("   [Sync] sticky green expired after empty/timeout wire")
                probe = WireProbeResult.failed("probe_timeout_empty")
            elif len(raw) == 0:
                print(
                    "   [Sync] peer state_root wire probe empty "
                    f"with {len(peers)} peer(s)"
                )
                self._wire_probe_fail_ts = time.time()
                if self.consistency.snapshot().consistent:
                    self._wire_sticky_empty_streak = int(
                        getattr(self, "_wire_sticky_empty_streak", 0) or 0
                    ) + 1
                    max_sticky = int(getattr(self, "_wire_sticky_empty_max", 3) or 3)
                    if self._wire_sticky_empty_streak < max_sticky:
                        print("   [Sync] wire probe backoff after timeout/empty")
                        return True
                    print("   [Sync] sticky green expired after empty/timeout wire")
                probe = WireProbeResult.failed("probe_empty")
            else:
                wire_roots = list(raw)
                self._wire_probe_fail_ts = 0.0
                self._wire_sticky_empty_streak = 0
                probe = WireProbeResult.succeeded(wire_roots=tuple(wire_roots))
        except Exception as exc:
            print(f"   [Sync] peer state_root wire probe failed: {exc}")
            self._wire_probe_fail_ts = time.time()
            probe = WireProbeResult.failed(str(exc))

        decision = self.consistency.apply_probe_evaluation(
            peers=peers,
            local_height=local_height,
            local_root=local_root,
            probe=probe,
        )
        snap = self.consistency.snapshot()
        if snap.reason_code == "state_root_mismatch":
            print(
                f"   State root mismatch vs peers: "
                f"{', '.join(snap.probe.mismatch_peers)}"
            )
        elif snap.state.value == "behind_open":
            print(
                "   Sync incomplete vs ahead peers — not tip-consistent yet "
                f"(local height={local_height})"
            )
        elif snap.reason_code == "no_same_height_match":
            print(
                "   No same-height peer root match — fail-closed "
                f"(local height={local_height})"
            )
        elif decision.trusted:
            print(
                f"   State consistent (root={local_root[:12]}... height={local_height})"
            )
        return bool(decision.trusted)

    def get_status(self) -> dict:
        local_height = self._local_height()
        peers = self._collect_p2p_peers()
        best_peer_height = 0
        for peer in peers:
            best_peer_height = max(best_peer_height, int(getattr(peer, "height", 0) or 0))

        state_consistent = bool(self.consistency.snapshot().consistent)
        probe = getattr(self, "_last_wire_probe_ok", None)
        cstat = self.consistency.status()

        return {
            "syncing": self.is_syncing,
            "peers": len(peers),
            "progress": self.sync_progress,
            "local_height": local_height,
            "best_peer_height": best_peer_height,
            "behind": max(0, best_peer_height - local_height),
            "state_consistent": state_consistent,
            # Unknown (never probed) is fail-closed False for status honesty.
            "wire_probe_ok": True if probe is True else False,
            "wire_probe_probed": probe is not None,
            "sync_fail": int(self._sync_fail),
            "last_sync_error": self._last_sync_error or "",
            "last_sync_ok_at": int(self._last_sync_ok_at or 0),
            "heads_skipped_no_head": int(
                getattr(self, "_heads_skipped_no_head", 0) or 0
            ),
            "native_sync_heads_no_invent": True,
            "native_sync_state_wire_only": True,
            "consistency_boundary": True,
            "sync_consistency_state": cstat.get("sync_consistency_state"),
            "sync_consistency_reason": cstat.get("sync_consistency_reason"),
            "sync_lockdown_total": cstat.get("sync_lockdown_total"),
        }

    def reset(self):
        self.is_syncing = False
        self.sync_progress = 0
