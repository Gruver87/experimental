"""CatchUpPathAService — ahead catch-up loop over ports (ADR 0004 Step A).

No ``asyncio``, no ``network.p2p_node``. I/O lives behind CatchUp* ports.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from sync.catchup.orchestrator import CatchUpOrchestrator
from sync.catchup.types import (
    CatchUpConfig,
    CatchUpOutcome,
    CatchUpPeerView,
)
from sync.ports import (
    CatchUpChainPort,
    CatchUpFetchPort,
    CatchUpProbePort,
    CatchUpSideEffectPort,
)

logger = logging.getLogger("Sync.CatchUp.PathA")


def _block_height(block: Mapping[str, Any], default: int = -1) -> int:
    try:
        if "height" in block and block.get("height") is not None:
            return int(block.get("height"))
        if "number" in block and block.get("number") is not None:
            return int(block.get("number"))
        return int(default)
    except (TypeError, ValueError):
        return int(default)


def _block_hash(block: Mapping[str, Any]) -> str:
    return str(block.get("hash") or block.get("block_hash") or "").strip()


class CatchUpPathAService:
    """Path A ahead sync: peer_height > local_height via port façades."""

    __slots__ = ("_chain", "_fetch", "_probe", "_side", "_orch")

    def __init__(
        self,
        chain: CatchUpChainPort,
        fetch: CatchUpFetchPort,
        probe: CatchUpProbePort,
        side: CatchUpSideEffectPort,
        orchestrator: Optional[CatchUpOrchestrator] = None,
    ) -> None:
        self._chain = chain
        self._fetch = fetch
        self._probe = probe
        self._side = side
        self._orch = orchestrator if orchestrator is not None else CatchUpOrchestrator()

    @property
    def orchestrator(self) -> CatchUpOrchestrator:
        return self._orch

    def run_ahead(
        self,
        peer: CatchUpPeerView,
        config: Optional[CatchUpConfig] = None,
    ) -> CatchUpOutcome:
        """Run ahead catch-up against ``peer``. Does not refresh consistency."""
        cfg = config if config is not None else CatchUpConfig(
            batch_size=max(1, int(self._side.batch_size() or 32))
        )
        try:
            return self._run_ahead_inner(peer, cfg)
        except Exception as exc:
            logger.exception("[PathA] run_ahead error peer=%s", peer.peer_id[:12])
            return CatchUpOutcome.error(
                "path_a_exception",
                local_height=int(self._chain.height() or 0),
                target_height=int(peer.height or 0),
                detail=str(exc),
            )

    def _run_ahead_inner(
        self, peer: CatchUpPeerView, cfg: CatchUpConfig
    ) -> CatchUpOutcome:
        local_h = int(self._chain.height() or 0)
        peer_h = int(peer.height or 0)
        needs_genesis = False
        ng = getattr(self._chain, "needs_genesis", None)
        if callable(ng):
            try:
                needs_genesis = bool(ng())
            except Exception as exc:
                logger.warning("[PathA] needs_genesis check failed: %s", exc)
                try:
                    needs_genesis = int(local_h or 0) <= 0
                except Exception:
                    needs_genesis = True
        # Empty follower tip is height 0; leader genesis is also height 0.
        # Still ahead of "no block" — do not skip as not_ahead.
        if peer_h < local_h or (peer_h == local_h and not needs_genesis):
            return CatchUpOutcome.skipped(
                local_height=local_h, target_height=peer_h, reason_code="not_ahead"
            )
        if peer_h < 0:
            return CatchUpOutcome.skipped(
                local_height=local_h, target_height=peer_h, reason_code="not_ahead"
            )

        # Ahead refuse (require head + optional local head↔height bind).
        local_blk = None
        head = str(peer.head_hash or "").strip()
        if head:
            try:
                local_blk = self._chain.get_block(head)
            except Exception as exc:
                logger.warning("[PathA] get_block(%s) for ahead-refuse failed: %s", head, exc)
                local_blk = None
        # When importing genesis into an empty tip, peer_height may equal local
        # reported height (0). Policy ahead_refuse treats equal heights as
        # not-ahead — pass a synthetic behind height for the refuse check only.
        refuse_local_h = -1 if needs_genesis and local_h == 0 else local_h
        ahead_refuse = self._orch.ahead_refuse_reason(
            local_height=refuse_local_h,
            peer_height=peer_h,
            peer_head=head,
            local_block_for_head=local_blk,
            require_head=bool(cfg.require_head),
        )
        if ahead_refuse:
            self._side.bump_refuse(ahead_refuse)
            return CatchUpOutcome.refused(
                ahead_refuse, local_height=local_h, target_height=peer_h
            )

        if cfg.tip_probe_enabled:
            tip_refuse = str(self._probe.local_tip_probe_refuse(peer) or "")
            if tip_refuse:
                self._side.bump_refuse(tip_refuse)
                return CatchUpOutcome.refused(
                    tip_refuse, local_height=local_h, target_height=peer_h
                )

        if cfg.peer_head_probe_enabled:
            head_refuse = str(self._probe.peer_head_probe_refuse(peer) or "")
            if head_refuse:
                self._side.bump_refuse(head_refuse)
                return CatchUpOutcome.refused(
                    head_refuse, local_height=local_h, target_height=peer_h
                )

        self._side.on_progress(
            f"Syncing from #{local_h} to #{peer_h} via {peer.peer_id[:8]}"
        )

        # Empty tip: start at genesis (#0). Non-empty tip at height 0 still
        # has block #0 locally — then cursor advances to 1 when peer is ahead.
        if needs_genesis:
            current = 0
        elif local_h == 0:
            current = 0 if peer_h == 0 else 1
        else:
            current = local_h + 1
        imported = 0
        batch_size = max(1, int(cfg.batch_size or self._side.batch_size() or 32))
        target = peer_h

        while self._side.is_running() and current <= target:
            batch_end = min(current + batch_size - 1, target)
            parent_hash = self._chain.expected_parent(current)
            blocks = self._fetch.fetch_blocks(
                peer.peer_id,
                int(current),
                int(batch_end),
                parent_hash,
                timeout=float(cfg.fetch_timeout),
            )
            if blocks is None:
                self._side.on_progress(
                    f"Sync stalled at #{current} (no blocks response)"
                )
                tip = int(self._chain.height() or 0)
                return CatchUpOutcome.stalled(
                    local_height=tip,
                    target_height=target,
                    imported=imported,
                    reason_code="fetch_stall",
                    detail=f"cursor={current}",
                )
            if not blocks:
                tip = int(self._chain.height() or 0)
                return CatchUpOutcome.incomplete(
                    local_height=tip,
                    target_height=target,
                    imported=imported,
                    reason_code="empty_batch",
                    detail=f"cursor={current}",
                )

            imported_any = False
            abort_batch = False
            for block_data in blocks:
                if not isinstance(block_data, Mapping):
                    abort_batch = True
                    break
                try:
                    outcome = self._import_one(
                        peer=peer,
                        cfg=cfg,
                        block_data=block_data,
                        expected_height=int(current),
                    )
                except Exception as exc:
                    tip = int(self._chain.height() or 0)
                    self._side.on_progress(
                        f"Sync block error at #{current}: {exc}"
                    )
                    return CatchUpOutcome.error(
                        "import_exception",
                        local_height=tip,
                        target_height=target,
                        imported=imported,
                        detail=str(exc),
                    )

                if outcome == "refuse":
                    abort_batch = True
                    break
                if outcome == "reorg":
                    # Cursor reset by _import_one via chain height.
                    current = int(self._chain.height() or 0) + 1
                    imported_any = True
                    abort_batch = True
                    break
                if outcome == "fail":
                    abort_batch = True
                    break
                # success
                h = _block_height(block_data, current)
                current = int(h) + 1
                imported += 1
                imported_any = True

            if not imported_any:
                tip = int(self._chain.height() or 0)
                return CatchUpOutcome.incomplete(
                    local_height=tip,
                    target_height=target,
                    imported=imported,
                    reason_code="batch_no_progress",
                    detail=f"cursor={current}",
                )

            # Soft-update claimed peer height floor to local tip (parity with P2P).
            tip_now = int(self._chain.height() or 0)
            self._side.set_peer_height(peer.peer_id, max(int(peer.height or 0), tip_now))
            # Refresh target if peer view was raised externally; keep original floor.
            target = max(target, int(peer.height or 0))

            if abort_batch and current > target:
                break

        tip = int(self._chain.height() or 0)
        reached_target = tip >= int(peer.height or 0)
        if reached_target:
            tip_refuse = self._orch.tip_head_at_height_refuse_reason(
                local_height=tip,
                peer_height=int(peer.height or 0),
                local_head=str(self._chain.head() or ""),
                peer_head=str(peer.head_hash or ""),
                enabled=bool(cfg.tip_head_bind),
            )
            if tip_refuse:
                self._side.bump_refuse(tip_refuse)
                self._side.on_progress(
                    f"Sync incomplete tip-head refuse {tip_refuse} tip=#{tip}"
                )
                return CatchUpOutcome.incomplete(
                    local_height=tip,
                    target_height=int(peer.height or 0),
                    imported=imported,
                    reason_code=tip_refuse,
                )
            self._side.on_progress(f"Sync complete. Our height: {tip}")
            return CatchUpOutcome.complete(
                local_height=tip,
                target_height=int(peer.height or 0),
                imported=imported,
            )

        self._side.on_progress(
            f"Sync incomplete. Our height: {tip} (peer target #{peer.height})"
        )
        return CatchUpOutcome.incomplete(
            local_height=tip,
            target_height=int(peer.height or 0),
            imported=imported,
            reason_code="incomplete",
        )

    def _import_one(
        self,
        *,
        peer: CatchUpPeerView,
        cfg: CatchUpConfig,
        block_data: Mapping[str, Any],
        expected_height: int,
    ) -> str:
        """Return ``ok`` | ``refuse`` | ``fail`` | ``reorg``."""
        cont = self._orch.height_continuity_refuse_reason(
            block_data,
            int(expected_height),
            enabled=bool(cfg.height_continuity_bind),
        )
        if cont:
            self._side.bump_refuse(cont)
            return "refuse"

        tip_h = int(self._chain.height() or 0)
        body_h = _block_height(block_data, -1)
        # Contiguous parent only when body is exactly tip+1 (parity with P2P).
        if (
            body_h >= 0
            and tip_h >= 0
            and body_h == tip_h + 1
            and bool(cfg.contiguous_parent_bind)
        ):
            contig = self._orch.contiguous_parent_refuse_reason(
                block_data,
                str(self._chain.head() or ""),
                enabled=True,
            )
            if contig:
                self._side.bump_refuse(contig)
                return "refuse"

        # Tip-height body must cite peer.head when bind enabled.
        peer_h = int(peer.height or 0)
        if (
            body_h >= 0
            and peer_h >= 0
            and body_h == peer_h
            and bool(cfg.tip_head_bind)
        ):
            want = str(peer.head_hash or "").strip()
            got = _block_hash(block_data)
            if want and got and want.lower() != got.lower():
                self._side.bump_refuse("catch_up_tip_head_mismatch")
                return "refuse"

        if self._chain.import_block(block_data):
            return "ok"

        self._side.note_import_fail(peer.peer_id)
        parent_hash = str(block_data.get("parent_hash") or "").strip()
        cand_hash = _block_hash(block_data)
        local_head = str(self._chain.head() or "").strip()
        # Failed +1 extend (parent is the current tip) is not a fork.
        if parent_hash and local_head and parent_hash.lower() == local_head.lower():
            fail_h = body_h if body_h >= 0 else expected_height
            self._side.on_progress(f"Import failed at #{fail_h}, aborting batch")
            return "fail"
        # Concurrent catch-up of a block we already have — do not roll back.
        if body_h >= 0:
            existing = None
            try:
                existing = self._chain.get_block(int(body_h))
            except Exception as exc:
                logger.warning("[PathA] get_block(%s) during import-fail check: %s", body_h, exc)
                existing = None
            if isinstance(existing, Mapping):
                exist_h = _block_hash(existing)
                if cand_hash and exist_h and cand_hash.lower() == exist_h.lower():
                    self._side.on_progress(
                        f"Duplicate #{body_h} already canonical, skip reorg"
                    )
                    return "fail"
        ancestor = None
        if parent_hash:
            try:
                ancestor = self._chain.find_ancestor_height(parent_hash)
            except Exception:
                ancestor = None
        if (
            ancestor is not None
            and int(ancestor) < int(self._chain.height() or 0)
        ):
            if self._chain.reorg_to_ancestor(int(ancestor)):
                self._side.on_progress(
                    f"Fork resolved — reorg to #{ancestor}, retry import"
                )
                return "reorg"
        fail_h = body_h if body_h >= 0 else expected_height
        self._side.on_progress(f"Import failed at #{fail_h}, aborting batch")
        return "fail"
