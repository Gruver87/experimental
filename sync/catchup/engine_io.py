"""SyncEngine ↔ CatchUp* port adapters (ADR 0004 Step C).

Duck-typed over ``SyncEngine.node`` — no P2P node module imports.
Implements the same CatchUp* ports Path A uses so ``fast_sync`` shares
``CatchUpPathAService.run_ahead`` instead of a private download/import loop.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

from crypto import native

logger = logging.getLogger("Sync.CatchUp.EngineIO")


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


class SyncEngineCatchUpIO:
    """One object implementing CatchUpChain + Fetch + Probe + SideEffect.

    Fetch materialises an ahead height-index once via ``engine.download_chain``
    (parent walk + ``_resolve_block``), validates contiguity before serving
    any batch, then returns height-range slices — same port contract as Path A.
    """

    __slots__ = (
        "_engine",
        "_peer_id",
        "_peer_head",
        "_target_height",
        "_batch_size",
        "_running",
        "_by_height",
        "_chain_ready",
        "_chain_ok",
        "_chain_error",
        "refuses",
        "import_fails",
        "peer_heights",
        "progress",
        "fetch_calls",
    )

    def __init__(
        self,
        engine: Any,
        *,
        peer_id: str,
        peer_head: str,
        target_height: int,
        batch_size: int = 32,
        running: bool = True,
    ) -> None:
        self._engine = engine
        self._peer_id = str(peer_id or "")
        self._peer_head = str(peer_head or "").strip()
        self._target_height = int(target_height or 0)
        self._batch_size = max(1, int(batch_size or 32))
        self._running = bool(running)
        self._by_height: Dict[int, dict] = {}
        self._chain_ready = False
        self._chain_ok = True
        self._chain_error = ""
        self.refuses: List[str] = []
        self.import_fails: List[str] = []
        self.peer_heights: Dict[str, int] = {}
        self.progress: List[str] = []
        self.fetch_calls: List[tuple] = []

    # ── CatchUpChainPort ─────────────────────────────────────────────────────

    def height(self) -> int:
        return int(self._engine._local_height())

    def needs_genesis(self) -> bool:
        """True when local store has no last block (import genesis from peer)."""
        checker = getattr(self._engine, "_local_needs_genesis", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception as exc:
                logger.warning("[EngineIO] needs_genesis checker failed: %s", exc)
                try:
                    return int(self._engine._local_height() or 0) <= 0
                except Exception:
                    return True
        bc = getattr(self._engine.node, "blockchain", None)
        if bc is None or not hasattr(bc, "get_last_block"):
            return False
        try:
            return bc.get_last_block() is None
        except Exception as exc:
            logger.warning("[EngineIO] get_last_block failed: %s", exc)
            try:
                return int(self.height() or 0) <= 0
            except Exception:
                return True

    def head(self) -> str:
        tip_h = self.height()
        blk = self.get_block(tip_h)
        if isinstance(blk, Mapping):
            return _block_hash(blk)
        node = getattr(self._engine, "node", None)
        if node is not None and hasattr(node, "head"):
            try:
                return str(node.head() or "")
            except Exception:
                return ""
        return ""

    def expected_parent(self, height: int) -> str:
        h = int(height)
        if h <= 0:
            return "0" * 64
        prev = self.get_block(h - 1)
        if isinstance(prev, Mapping):
            ph = _block_hash(prev)
            if ph:
                return ph
        tip = self.head()
        return tip or ("0" * 64)

    def get_block(self, height_or_hash: Any) -> Any:
        node = self._engine.node
        bc = getattr(node, "blockchain", None)
        if isinstance(height_or_hash, int) or (
            isinstance(height_or_hash, str) and str(height_or_hash).isdigit()
        ):
            h = int(height_or_hash)
            if h in self._by_height:
                return self._by_height[h]
            if bc is not None and hasattr(bc, "get_block"):
                try:
                    return bc.get_block(h)
                except Exception as exc:
                    logger.warning("[EngineIO] get_block(%s) failed: %s", h, exc)
                    return None
            return None
        key = str(height_or_hash or "").strip()
        if not key:
            return None
        for blk in self._by_height.values():
            if _block_hash(blk) == key:
                return blk
        if hasattr(self._engine, "_resolve_block"):
            return self._engine._resolve_block(key)
        if bc is not None and hasattr(bc, "get_block_by_hash"):
            try:
                return bc.get_block_by_hash(key)
            except Exception as exc:
                logger.warning("[EngineIO] get_block_by_hash failed: %s", exc)
                return None
        return None

    def import_block(self, data: Mapping[str, Any]) -> bool:
        node = self._engine.node
        blk = dict(data)
        try:
            if hasattr(node, "import_block"):
                ok = bool(node.import_block(blk))
            elif hasattr(node, "consensus") and hasattr(node.consensus, "add_block"):
                ok = bool(node.consensus.add_block(blk))
            else:
                return False
            if ok:
                h = _block_height(blk, -1)
                hh = _block_hash(blk)
                if h >= 0:
                    self._by_height[h] = blk
                if hh:
                    # Keep in-memory index coherent for subsequent expected_parent.
                    pass
            return ok
        except Exception as exc:
            logger.warning("[EngineIO] import_block failed: %s", exc)
            return False

    def find_ancestor_height(self, parent_hash: str) -> Optional[int]:
        key = str(parent_hash or "").strip()
        if not key:
            return None
        bc = getattr(self._engine.node, "blockchain", None)
        if bc is not None and hasattr(bc, "find_ancestor_height"):
            try:
                return bc.find_ancestor_height(key)
            except Exception as exc:
                logger.warning("[EngineIO] find_ancestor_height failed: %s", exc)
                return None
        blk = self.get_block(key)
        if isinstance(blk, Mapping):
            h = _block_height(blk, -1)
            return h if h >= 0 else None
        return None

    def reorg_to_ancestor(self, height: int) -> bool:
        bc = getattr(self._engine.node, "blockchain", None)
        if bc is None or not hasattr(bc, "reorg_to_ancestor"):
            return False
        try:
            return bool(bc.reorg_to_ancestor(int(height)))
        except Exception as exc:
            logger.warning("[EngineIO] reorg_to_ancestor failed: %s", exc)
            return False

    # ── CatchUpFetchPort ─────────────────────────────────────────────────────

    def fetch_blocks(
        self,
        peer_id: str,
        from_height: int,
        to_height: int,
        parent_hash: str,
        *,
        timeout: float = 45.0,
    ) -> Optional[Sequence[Mapping[str, Any]]]:
        self.fetch_calls.append(
            (
                str(peer_id),
                int(from_height),
                int(to_height),
                str(parent_hash or ""),
                float(timeout),
            )
        )
        self._ensure_ahead_index()
        if not self._chain_ok:
            # Contiguity / download failure — refuse to feed Path A any body.
            return None
        out: List[Mapping[str, Any]] = []
        for h in range(int(from_height), int(to_height) + 1):
            blk = self._by_height.get(h)
            if blk is None:
                # Partial range: return what we have; empty → Path A incomplete.
                break
            out.append(blk)
        return out

    def _ensure_ahead_index(self) -> None:
        if self._chain_ready:
            return
        self._chain_ready = True
        engine = self._engine
        local_h = int(engine._local_height())
        head = self._peer_head
        if not head:
            self._chain_ok = False
            self._chain_error = "no_peer_head"
            return
        needs_genesis = self.needs_genesis()
        # Empty DB: stop_at=-1 so height-0 genesis is included (0 <= 0 would drop it).
        stop_h = -1 if needs_genesis else local_h
        try:
            chain = list(engine.download_chain(head, stop_at_height=stop_h) or [])
        except Exception as exc:
            self._chain_ok = False
            self._chain_error = f"download:{exc}"
            return
        # Genesis empty-DB floor: allow height 0 when local tip is empty.
        bc = getattr(engine.node, "blockchain", None)
        import_floor = -1 if needs_genesis else local_h
        target = int(self._target_height or 0)
        filtered: List[dict] = []
        for block in chain:
            if not isinstance(block, Mapping):
                continue
            h = _block_height(block, -1)
            if h <= import_floor:
                continue
            if target > 0 and h > target:
                continue
            filtered.append(dict(block))
        filtered.sort(key=lambda b: _block_height(b, 0))
        if needs_genesis and not filtered:
            self._chain_ok = False
            self._chain_error = "genesis_download_empty"
            return
        if filtered:
            # Contiguity gate: first block height must equal start_height+1.
            # Empty tip → start_height=-1 so genesis (#0) validates.
            start_height = -1 if needs_genesis else local_h
            prev_hash = "0" * 64 if needs_genesis else ""
            if not needs_genesis and local_h >= 0 and bc is not None and hasattr(bc, "get_block"):
                local_tip = bc.get_block(local_h)
                if isinstance(local_tip, Mapping):
                    prev_hash = _block_hash(local_tip)
            if not native.validate_imported_block_chain(
                filtered,
                expected_parent_hash=prev_hash,
                start_height=start_height,
            ):
                self._chain_ok = False
                self._chain_error = "non_contiguous_chain"
                self._by_height = {}
                return
        for block in filtered:
            h = _block_height(block, -1)
            if h >= 0:
                self._by_height[h] = block
        self._chain_ok = True
        self._chain_error = ""

    # ── CatchUpProbePort ─────────────────────────────────────────────────────

    def local_tip_probe_refuse(self, peer: Any) -> str:
        """Refuse ahead catch-up when first imported block does not extend local tip."""
        local_h = int(self.height() or 0)
        peer_h = int(getattr(peer, "height", 0) or self._target_height or 0)
        if peer_h <= local_h or local_h <= 0:
            return ""
        self._ensure_ahead_index()
        first = self._by_height.get(local_h + 1)
        if not isinstance(first, Mapping):
            return ""
        parent = str(first.get("parent_hash") or "").strip()
        local_tip = self.head()
        if parent and local_tip and parent.lower() != local_tip.lower():
            return "catch_up_tip_head_mismatch"
        return ""

    def peer_head_probe_refuse(self, peer: Any) -> str:
        """Refuse when downloaded head hash/height does not match the peer claim."""
        local_h = int(self.height() or 0)
        peer_h = int(getattr(peer, "height", 0) or self._target_height or 0)
        if peer_h <= local_h:
            return ""
        self._ensure_ahead_index()
        if not self._chain_ok:
            return str(self._chain_error or "catch_up_peer_head_probe_failed")
        head = str(getattr(peer, "head_hash", "") or self._peer_head or "").strip()
        blk = self._by_height.get(peer_h)
        if not isinstance(blk, Mapping):
            return "catch_up_peer_head_probe_failed"
        got = _block_hash(blk)
        if head and got and got.lower() != head.lower():
            return "catch_up_peer_head_hash_mismatch"
        return ""

    # ── CatchUpSideEffectPort ────────────────────────────────────────────────

    def bump_refuse(self, reason: str) -> None:
        self.refuses.append(str(reason or ""))

    def note_import_fail(self, peer_id: str) -> None:
        self.import_fails.append(str(peer_id or ""))
        # Parity with legacy SyncEngine.fast_sync: hard import fail aborts
        # the whole catch-up (do not spin re-fetching the same cursor).
        self._running = False

    def set_peer_height(self, peer_id: str, height: int) -> None:
        self.peer_heights[str(peer_id)] = int(height)

    def is_running(self) -> bool:
        return bool(self._running)

    def batch_size(self) -> int:
        return int(self._batch_size)

    def on_progress(self, message: str) -> None:
        msg = str(message or "")
        self.progress.append(msg)
        print(f"[Sync] {msg}")
