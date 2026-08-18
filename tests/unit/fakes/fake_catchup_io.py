"""In-memory CatchUp* port façade for Path A unit tests (ADR 0004)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence


class FakeCatchUpIO:
    """Implements CatchUpChainPort + Fetch + Probe + SideEffect in one object."""

    def __init__(
        self,
        *,
        height: int = 0,
        head: str = "",
        blocks_by_hash: Optional[Dict[str, dict]] = None,
        blocks_by_height: Optional[Dict[int, dict]] = None,
        batch_size: int = 2,
        running: bool = True,
        tip_probe_refuse: str = "",
        peer_head_probe_refuse: str = "",
        fetch_plan: Optional[List[Optional[Sequence[Mapping[str, Any]]]]] = None,
        fail_import_heights: Optional[Sequence[int]] = None,
        ancestors: Optional[Dict[str, int]] = None,
        reorg_ok: bool = True,
    ) -> None:
        self._height = int(height)
        self._head = str(head or "")
        self._by_hash = dict(blocks_by_hash or {})
        self._by_height = dict(blocks_by_height or {})
        for h, blk in list(self._by_height.items()):
            hh = str(blk.get("hash") or blk.get("block_hash") or "")
            if hh and hh not in self._by_hash:
                self._by_hash[hh] = blk
        self._batch_size = max(1, int(batch_size))
        self._running = bool(running)
        self._tip_probe_refuse = str(tip_probe_refuse or "")
        self._peer_head_probe_refuse = str(peer_head_probe_refuse or "")
        self._fetch_plan: List[Optional[Sequence[Mapping[str, Any]]]] = list(
            fetch_plan or []
        )
        self._fetch_idx = 0
        self._fail_import = set(int(x) for x in (fail_import_heights or ()))
        self._ancestors = dict(ancestors or {})
        self._reorg_ok = bool(reorg_ok)
        self.refuses: List[str] = []
        self.import_fails: List[str] = []
        self.peer_heights: Dict[str, int] = {}
        self.progress: List[str] = []
        self.imported: List[dict] = []
        self.fetch_calls: List[tuple] = []

    # ── CatchUpChainPort ─────────────────────────────────────────────────────

    def height(self) -> int:
        return int(self._height)

    def head(self) -> str:
        return str(self._head or "")

    def expected_parent(self, height: int) -> str:
        h = int(height)
        if h <= 0:
            return "0" * 64
        prev = self._by_height.get(h - 1)
        if isinstance(prev, dict):
            ph = str(prev.get("hash") or prev.get("block_hash") or "").strip()
            if ph:
                return ph
        return str(self._head or "") or ("0" * 64)

    def get_block(self, height_or_hash: Any) -> Any:
        if isinstance(height_or_hash, int) or (
            isinstance(height_or_hash, str) and height_or_hash.isdigit()
        ):
            return self._by_height.get(int(height_or_hash))
        key = str(height_or_hash or "").strip()
        return self._by_hash.get(key)

    def import_block(self, data: Mapping[str, Any]) -> bool:
        try:
            raw = data.get("height", data.get("number", None))
            h = int(raw) if raw is not None else -1
        except (TypeError, ValueError):
            h = -1
        if h in self._fail_import:
            return False
        blk = dict(data)
        hh = str(blk.get("hash") or blk.get("block_hash") or f"h{h}").strip()
        blk["hash"] = hh
        blk["height"] = h
        self._by_hash[hh] = blk
        self._by_height[h] = blk
        self._height = max(self._height, h)
        self._head = hh
        self.imported.append(blk)
        return True

    def find_ancestor_height(self, parent_hash: str) -> Optional[int]:
        key = str(parent_hash or "").strip()
        if key in self._ancestors:
            return int(self._ancestors[key])
        blk = self._by_hash.get(key)
        if isinstance(blk, dict):
            try:
                raw = blk.get("height", blk.get("number", None))
                return int(raw) if raw is not None else None
            except (TypeError, ValueError):
                return None
        return None

    def reorg_to_ancestor(self, height: int) -> bool:
        if not self._reorg_ok:
            return False
        h = int(height)
        self._height = h
        tip = self._by_height.get(h)
        if isinstance(tip, dict):
            self._head = str(tip.get("hash") or tip.get("block_hash") or "")
        else:
            self._head = ""
        # Drop higher blocks from maps (soft).
        for kh in list(self._by_height.keys()):
            if int(kh) > h:
                gone = self._by_height.pop(kh)
                hh = str(gone.get("hash") or "")
                self._by_hash.pop(hh, None)
        return True

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
            (peer_id, int(from_height), int(to_height), str(parent_hash), float(timeout))
        )
        if self._fetch_idx >= len(self._fetch_plan):
            return None
        item = self._fetch_plan[self._fetch_idx]
        self._fetch_idx += 1
        return item

    # ── CatchUpProbePort ─────────────────────────────────────────────────────

    def local_tip_probe_refuse(self, peer: Any) -> str:
        return str(self._tip_probe_refuse or "")

    def peer_head_probe_refuse(self, peer: Any) -> str:
        return str(self._peer_head_probe_refuse or "")

    # ── CatchUpSideEffectPort ────────────────────────────────────────────────

    def bump_refuse(self, reason: str) -> None:
        self.refuses.append(str(reason or ""))

    def note_import_fail(self, peer_id: str) -> None:
        self.import_fails.append(str(peer_id or ""))

    def set_peer_height(self, peer_id: str, height: int) -> None:
        self.peer_heights[str(peer_id)] = int(height)

    def is_running(self) -> bool:
        return bool(self._running)

    def batch_size(self) -> int:
        return int(self._batch_size)

    def on_progress(self, message: str) -> None:
        self.progress.append(str(message or ""))
